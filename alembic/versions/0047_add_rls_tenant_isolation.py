"""Enable PostgreSQL RLS tenant isolation on high-risk multi-tenant tables.

Revision ID: 0047_add_rls_tenant_isolation
Revises: 0046_list_query_indexes
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0047_add_rls_tenant_isolation"
down_revision: Union[str, Sequence[str], None] = "0046_list_query_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# table -> tenant column name
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


def _session_role_ident() -> str:
    """SQL identifier for the role running migrations (matches POSTGRES_USER)."""
    from sqlalchemy import text

    return op.get_bind().execute(text("SELECT quote_ident(session_user::text)")).scalar_one()


def _enable_policies(table: str, tenant_col: str, bypass_role: str) -> None:
    from sqlalchemy import text

    connection = op.get_bind()
    present = connection.execute(
        text("SELECT to_regclass(:qname) IS NOT NULL"),
        {"qname": table},
    ).scalar_one()
    if not present:
        return
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY;')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY;')
    op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}";')
    op.execute(f'DROP POLICY IF EXISTS superuser_bypass ON "{table}";')
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON "{table}"
        USING (
            "{tenant_col}" = current_setting('app.current_org_id', true)::bigint
        );
        """
    )
    op.execute(
        f"""
        CREATE POLICY superuser_bypass ON "{table}"
        TO {bypass_role}
        USING (true);
        """
    )


def _disable_policies(table: str) -> None:
    from sqlalchemy import text

    present = op.get_bind().execute(
        text("SELECT to_regclass(:qname) IS NOT NULL"),
        {"qname": table},
    ).scalar_one()
    if not present:
        return
    op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}";')
    op.execute(f'DROP POLICY IF EXISTS superuser_bypass ON "{table}";')
    op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY;')


def upgrade() -> None:
    bypass_role = _session_role_ident()
    for table, tenant_col in TENANT_TABLES.items():
        _enable_policies(table, tenant_col, bypass_role)


def downgrade() -> None:
    for table in TENANT_TABLES.keys():
        _disable_policies(table)
