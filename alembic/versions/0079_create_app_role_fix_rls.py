"""Create thiramai_app role and harden RLS tenant_isolation.

Two-part P0 security fix:

1. Create a dedicated, **non-superuser, non-bypass** application role
   (``thiramai_app``) for the runtime web/worker connection. Migrations
   continue to run as the admin role (``thiramai`` / current_user) which
   keeps its ``superuser_bypass`` policy from 0077.

2. Rewrite the ``tenant_isolation`` policy on every table in
   ``alembic/versions/0047_add_rls_tenant_isolation.TENANT_TABLES``
   so it is **permissive when ``app.current_org_id`` is unset** (auth /
   system bootstrap paths) and **strict when it is set** (tenant
   requests). This is the *known compromise* documented in
   ``docs/deployment/P0_SECURITY_FIXES.md`` — the alternative requires
   refactoring login to a stored procedure or pre-auth admin session.

Revision ID: 0079_create_app_role_fix_rls
Revises: 0078_add_ai_decisions_table
"""

from __future__ import annotations

import os
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "0079_create_app_role_fix_rls"
down_revision: Union[str, Sequence[str], None] = "0078_add_ai_decisions_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Mirrors alembic/versions/0047_add_rls_tenant_isolation.TENANT_TABLES;
# duplicated here to keep this migration self-contained and importable
# even if 0047 is later refactored.
TENANT_TABLES: dict[str, str] = {
    "generated_websites": "organization_id",
    "roles": "org_id",
    "user_organization_memberships": "organization_id",
    "executive_vault_documents": "organization_id",
    "research_vault": "organization_id",
    "research_corrections": "organization_id",
    "personal_suggestion_feedback": "organization_id",
    "approvals": "organization_id",
    "learning_logs": "organization_id",
    "system_audit_logs": "organization_id",
    "audit_logs": "org_id",
    "control_plane_alerts": "org_id",
    "control_plane_jobs": "org_id",
    "saas_subscriptions": "org_id",
    "saas_usage_metrics": "org_id",
    "autonomy_settings": "org_id",
    "autonomy_feedback": "org_id",
    "assets": "organization_id",
    "debts": "organization_id",
    "notifications": "organization_id",
    "compliance_cases": "organization_id",
    "comms_inbox": "organization_id",
    "departments": "organization_id",
    "staff_profiles": "organization_id",
    "operational_expenses": "organization_id",
    "agro_subsidy_cases": "organization_id",
    "business_tasks": "organization_id",
    "invoices": "organization_id",
    "bills": "organization_id",
    "factory_billing_hold": "organization_id",
    "project_stages": "organization_id",
    "equipment": "organization_id",
    "ai_hitl_feedback": "organization_id",
    "ai_rule_weights": "organization_id",
    "ledger_transactions": "organization_id",
    "background_jobs": "organization_id",
    "inventory_items": "organization_id",
    "stock_movements": "organization_id",
    "suppliers": "organization_id",
    "purchase_orders": "organization_id",
    "supplier_payments": "organization_id",
    "organization_liquidity": "organization_id",
    "payments": "organization_id",
    "gst_records": "organization_id",
    "raw_materials": "organization_id",
    "ai_decisions": "organization_id",
    "usage_logs": "org_id",
    "personal_meetings": "organization_id",
    "jarvis_proactive_alerts": "organization_id",
    "jarvis_goals": "organization_id",
    "jarvis_agent_event_queue": "organization_id",
    "research_documents": "organization_id",
    "govt_schemes": "organization_id",
    "financial_audit_logs": "organization_id",
}


# Default password is overridable via env so this migration is reproducible
# without leaking secrets into source control. Operators SHOULD set
# THIRAMAI_APP_DB_PASSWORD before running migrations in production.
_DEFAULT_APP_ROLE = "thiramai_app"
# Default matches scripts/init-db.sh and the DATABASE_URL placeholder shipped in
# .env.production. Operators override via env (THIRAMAI_APP_DB_PASSWORD) in real deployments.
_DEFAULT_APP_PASSWORD = os.getenv("THIRAMAI_APP_DB_PASSWORD") or "thiramai_2026"


def _table_exists(name: str) -> bool:
    return bool(
        op.get_bind()
        .execute(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": name})
        .scalar_one()
    )


def _set_permissive_tenant_policy(table: str, tenant_col: str) -> None:
    op.execute(text(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"'))
    op.execute(
        text(
            f"""
            CREATE POLICY tenant_isolation ON "{table}"
            USING (
                current_setting('app.current_org_id', true) IS NULL
                OR current_setting('app.current_org_id', true) = ''
                OR "{tenant_col}" = current_setting('app.current_org_id', true)::bigint
            )
            """
        )
    )


def _set_strict_tenant_policy(table: str, tenant_col: str) -> None:
    op.execute(text(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"'))
    op.execute(
        text(
            f"""
            CREATE POLICY tenant_isolation ON "{table}"
            USING (
                "{tenant_col}" = current_setting('app.current_org_id', true)::bigint
            )
            """
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    dialect = str(bind.dialect.name).lower() if bind is not None else "postgresql"
    if dialect != "postgresql":
        return

    # ------------------------------------------------------------------
    # 1) Ensure thiramai_app role exists with restricted privileges.
    #
    # `scripts/init-db.sh` already creates the role on a fresh data volume
    # with the correct attributes (NOSUPERUSER NOBYPASSRLS NOCREATEROLE
    # NOCREATEDB). We deliberately DO NOT run `ALTER ROLE … NOSUPERUSER`
    # here:
    #
    #   - Setting / clearing the SUPERUSER attribute requires the executor
    #     to be a SUPERUSER. Even though the migration role usually is, the
    #     statement is fragile (it fails the entire transaction and rolls
    #     every prior migration back when run by a non-SUPERUSER admin
    #     such as a managed-Postgres role with `BYPASSRLS` only).
    #   - Re-asserting attributes that init-db.sh already set is redundant.
    #
    # If the role does not exist (e.g. someone reset the database without
    # the init script), this block creates it. Otherwise it is a no-op.
    # ------------------------------------------------------------------
    bind.execute(
        text(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_DEFAULT_APP_ROLE}') THEN
                    EXECUTE format(
                        'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB',
                        '{_DEFAULT_APP_ROLE}',
                        '{_DEFAULT_APP_PASSWORD}'
                    );
                END IF;
            END
            $$;
            """
        )
    )

    # Connection + schema + DML grants. All idempotent — repeated runs are
    # harmless. Granting SELECT/INSERT/UPDATE/DELETE on existing tables
    # picks up everything created by migrations 0001..0078; default
    # privileges cover anything created later (e.g. 0078's ai_decisions).
    bind.execute(
        text(
            f"""
            GRANT CONNECT ON DATABASE {bind.engine.url.database} TO {_DEFAULT_APP_ROLE};
            GRANT USAGE ON SCHEMA public TO {_DEFAULT_APP_ROLE};
            GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {_DEFAULT_APP_ROLE};
            GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {_DEFAULT_APP_ROLE};
            ALTER DEFAULT PRIVILEGES IN SCHEMA public
                GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {_DEFAULT_APP_ROLE};
            ALTER DEFAULT PRIVILEGES IN SCHEMA public
                GRANT USAGE, SELECT ON SEQUENCES TO {_DEFAULT_APP_ROLE};
            """
        )
    )

    # ------------------------------------------------------------------
    # 2) Replace tenant_isolation with permissive-on-unset policy on every
    #    tenant table that exists. (superuser_bypass policies remain TO the
    #    migration role only — see migration 0077.)
    # ------------------------------------------------------------------
    for table, tenant_col in TENANT_TABLES.items():
        if not _table_exists(table):
            continue
        _set_permissive_tenant_policy(table, tenant_col)


def downgrade() -> None:
    bind = op.get_bind()
    dialect = str(bind.dialect.name).lower() if bind is not None else "postgresql"
    if dialect != "postgresql":
        return

    # Restore the original strict policy from 0047. We do not drop the
    # ``thiramai_app`` role on downgrade because production data may already
    # be owned by it; operators must run ``DROP ROLE`` explicitly if needed.
    for table, tenant_col in TENANT_TABLES.items():
        if not _table_exists(table):
            continue
        _set_strict_tenant_policy(table, tenant_col)
