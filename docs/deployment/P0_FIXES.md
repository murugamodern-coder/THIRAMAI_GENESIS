# P0 Critical Security Fixes

This change closes both **P0** findings from the
[CTO audit (2026-05)](../audit/CTO_AUDIT_2026_05.md):

1. **RLS enforcement was broken** — `core/database.py` issued
   `SET LOCAL row_security = force`, which PostgreSQL rejects (the
   `row_security` GUC accepts `on`/`off` only). The exception was then
   silently swallowed, hiding a multi-tenant data-isolation regression.
2. **The web service connected as the `thiramai` superuser**, which
   migration 0047 grants `superuser_bypass USING (true)` on every tenant
   table — RLS was effectively disabled for every API request.

## What was fixed

### 1. `core/database.py` — valid syntax, visible failures

| Before | After |
| --- | --- |
| `session.execute(text("SET LOCAL row_security = force"))` | `session.execute(text("SET LOCAL row_security = on"))` |
| `try: ... except Exception: return` (silent) | `try: ... except Exception: log + raise` |

Tenant tables already have **`FORCE ROW LEVEL SECURITY`** at the table
level (set by migration 0047), so `row_security = on` is sufficient.
The `_session_after_begin_set_rls` SQLAlchemy listener now raises on
any RLS bootstrap failure so future regressions cannot silently disable
isolation.

### 2. `alembic/versions/0079_create_app_role_fix_rls.py`

- Creates **`thiramai_app`** role with
  `LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB` and the usual
  `SELECT/INSERT/UPDATE/DELETE` on `public` plus default privileges so
  future tables are auto-granted.
- Replaces the strict `tenant_isolation` policy on every table in
  `TENANT_TABLES` with a **permissive-on-unset** form so the auth flow
  (which must read `roles` / `user_organization_memberships` before it
  knows the org) keeps working under the restricted role:

  ```sql
  CREATE POLICY tenant_isolation ON "<table>"
  USING (
      current_setting('app.current_org_id', true) IS NULL
      OR current_setting('app.current_org_id', true) = ''
      OR "<tenant_col>" = current_setting('app.current_org_id', true)::bigint
  );
  ```

- The `superuser_bypass` policies (`TO <migration_role>`) installed by
  migration 0077 are unchanged: only the migration role bypasses RLS;
  `thiramai_app` does not.

### 3. `alembic/env.py`

- Prefers `ADMIN_DATABASE_URL` (or `ALEMBIC_DATABASE_URL`) so migrations
  always run as the privileged role, even though the runtime
  `DATABASE_URL` now points at `thiramai_app`.

### 4. `scripts/init-db.sh`

- Postgres entrypoint init (runs once on a fresh data volume).
- Creates `thiramai_app` with the password from `THIRAMAI_APP_DB_PASSWORD`
  (default `app_password_secure_2026`, matching the placeholder in
  `.env.production`).
- Idempotent: if the role exists it re-asserts `NOSUPERUSER NOBYPASSRLS`
  and updates the password.

### 5. `docker-compose.production.yml`

- `db` service mounts `./scripts/init-db.sh:/docker-entrypoint-initdb.d/10-thiramai-app-role.sh:ro`
  and receives `THIRAMAI_APP_DB_PASSWORD`.
- `web` service receives `ADMIN_DATABASE_URL` and `THIRAMAI_APP_DB_PASSWORD`.
- `worker-jobs` and `worker-alerts` connect via `ADMIN_DATABASE_URL`
  because they run system-wide jobs with `THIRAMAI_RLS_BYPASS=1` and
  must use a role that can actually bypass RLS.

### 6. `.env.production` / `.env.production.example`

- New: `ADMIN_DATABASE_URL` (admin) and `THIRAMAI_APP_DB_PASSWORD`.
- `DATABASE_URL` switched to `thiramai_app`.
- `THIRAMAI_EXPECTED_DB_REVISION=0079_create_app_role_fix_rls`.

### 7. `core/migration_head.py`

- `EXPECTED_ALEMBIC_REVISION = "0079_create_app_role_fix_rls"`.

## Manual deployment

This change requires a `web` rebuild because `core/database.py` is
baked into the runtime image. If passwords change you must also
recreate the database volume.

### 1. Rebuild the web image

```bash
docker compose -f docker-compose.production.yml --env-file .env.production build web
```

### 2. Update passwords in `.env.production`

Replace the placeholders with strong secrets and keep them aligned —
`DATABASE_URL` password must equal `THIRAMAI_APP_DB_PASSWORD`, and
`POSTGRES_PASSWORD` must equal the password in `ADMIN_DATABASE_URL`:

```bash
POSTGRES_PASSWORD=<your_strong_admin_password>
ADMIN_DATABASE_URL=postgresql+psycopg2://thiramai:<your_strong_admin_password>@db:5432/thiramai
DATABASE_URL=postgresql+psycopg2://thiramai_app:<your_strong_app_password>@db:5432/thiramai
THIRAMAI_APP_DB_PASSWORD=<your_strong_app_password>
```

### 3. Recreate the database (applies the init script)

```bash
docker compose -f docker-compose.production.yml --env-file .env.production down -v
docker compose -f docker-compose.production.yml --env-file .env.production up -d db
sleep 15
```

### 4. Start everything

```bash
docker compose -f docker-compose.production.yml --env-file .env.production up -d
sleep 20
```

### 5. Apply migrations (`thiramai_app` role gets `tenant_isolation` rewritten)

```bash
docker compose -f docker-compose.production.yml --env-file .env.production \
    exec web alembic upgrade head
```

Output should show `Running upgrade 0078_add_ai_decisions_table -> 0079_create_app_role_fix_rls`.

### 6. Verify the role

```bash
docker compose -f docker-compose.production.yml --env-file .env.production \
    exec -T db psql -U thiramai -d thiramai -c \
    "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname IN ('thiramai','thiramai_app')"
```

Expected:

```
   rolname    | rolsuper | rolbypassrls
--------------+----------+--------------
 thiramai     | t        | t
 thiramai_app | f        | f
```

### 7. Verify RLS is on globally

```bash
docker compose -f docker-compose.production.yml --env-file .env.production \
    exec -T db psql -U thiramai -d thiramai -c "SHOW row_security"
# Expected: on
```

### 8. Smoke-test login + decision

```bash
curl -s -X POST http://localhost:8000/auth/login \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "username=admin_king&password=thiramai_2026"
# Expected: { "access_token": "...", "token_type": "bearer", ... }

TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "username=admin_king&password=thiramai_2026" | jq -r '.access_token')

curl -s -X POST http://localhost:8000/chat/decision \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"message":"Should I invest in gold?"}'
# Expected: a JSON bundle with decision_brain_source = "policy_engine" and a decision_id
```

## Verification checklist

- [ ] Migration 0079 applied (`alembic_version.version_num` = `0079_create_app_role_fix_rls`)
- [ ] `thiramai_app` exists, `rolsuper=f`, `rolbypassrls=f`
- [ ] `DATABASE_URL` in the running web container starts with `thiramai_app:`
- [ ] `SHOW row_security` returns `on`
- [ ] `POST /auth/login` returns a JWT
- [ ] `POST /chat/decision` returns 200 and persists to `ai_decisions`
- [ ] No `row_security` errors in `docker compose logs web`

## Security impact

**Before:** the `force` syntax bug made every tenant session error on
`SET LOCAL`; the silent `except` masked it; meanwhile the web role
unconditionally bypassed RLS via `superuser_bypass`. Cross-tenant
isolation was effectively at the application-WHERE-clause layer only.

**After:** RLS GUC is set with valid syntax; failures are visible; the
runtime role cannot bypass RLS; `tenant_isolation` filters every
tenant-scoped query once `app.current_org_id` is set; pre-auth queries
remain functional via the permissive-on-unset clause.

## Trade-off and follow-up

The permissive-on-unset clause means a future code path that forgets
to call `set_current_org_id` would see all rows. The follow-up is to
refactor login/auth to a `SECURITY DEFINER` stored procedure (or a
dedicated bootstrap session that fetches `org_id` first) so the strict
`tenant_isolation` policy from migration 0047 can be restored. Until
then:

- `_session_after_begin_set_rls` raises on any RLS bootstrap failure.
- `tenant_session_scope` writes the GUC explicitly and adds a guard
  against tenant-less SELECTs.
- Workers run with `THIRAMAI_RLS_BYPASS=1` and connect as the admin
  role for system-wide jobs.

## Rollback

If the role flip causes auth regressions in your environment, revert
just the `DATABASE_URL` value back to the admin role and recreate the
web service:

```bash
# .env.production
DATABASE_URL=postgresql+psycopg2://thiramai:<admin password>@db:5432/thiramai

docker compose -f docker-compose.production.yml --env-file .env.production \
    up -d --force-recreate web
```

You can also `alembic downgrade 0078_add_ai_decisions_table` to restore
the strict `tenant_isolation` policy. The `thiramai_app` role is left
in place because production data may already reference it; drop
manually if needed.
