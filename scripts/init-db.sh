#!/bin/bash
# Postgres entrypoint init script — runs ONLY on a fresh data volume.
# For existing deployments, alembic migration 0079 is the source of truth.
set -e

APP_ROLE="thiramai_app"
# Default kept in sync with alembic/versions/0079_create_app_role_fix_rls.py
# and the DATABASE_URL placeholder in .env.production. Operators override via env.
APP_PASS="${THIRAMAI_APP_DB_PASSWORD:-thiramai_2026}"

echo "init-db: ensuring ${APP_ROLE} role exists in ${POSTGRES_DB} ..."

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${APP_ROLE}') THEN
            EXECUTE format(
                'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB',
                '${APP_ROLE}',
                '${APP_PASS}'
            );
            RAISE NOTICE 'init-db: created role %', '${APP_ROLE}';
        ELSE
            EXECUTE format('ALTER ROLE %I NOSUPERUSER NOBYPASSRLS', '${APP_ROLE}');
            EXECUTE format('ALTER ROLE %I WITH PASSWORD %L', '${APP_ROLE}', '${APP_PASS}');
            RAISE NOTICE 'init-db: updated role %', '${APP_ROLE}';
        END IF;
    END
    \$\$;

    GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO ${APP_ROLE};
    GRANT USAGE ON SCHEMA public TO ${APP_ROLE};
    -- Table-level grants applied by migration 0079 once the schema exists.
EOSQL

echo "init-db: done."
