"""Phase 8: composite and supporting indexes for tenant/time/status queries.

Revision ID: 0007_performance_indexing
Revises: 0006_factory_v2_expansion
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0007_performance_indexing"
down_revision: Union[str, Sequence[str], None] = "0006_factory_v2_expansion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Tenant + time / status patterns (list filters, dashboards, queues).
    # if_not_exists: baseline db/*.sql may already have created the same names (IF NOT EXISTS).
    op.create_index(
        "ix_approvals_org_status_created",
        "approvals",
        ["organization_id", "status", "created_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_bills_org_created",
        "bills",
        ["organization_id", "created_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_notifications_org_created",
        "notifications",
        ["organization_id", "created_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_background_jobs_status_created",
        "background_jobs",
        ["status", "created_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_background_jobs_org_created",
        "background_jobs",
        ["organization_id", "created_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_learning_logs_org_created",
        "learning_logs",
        ["organization_id", "created_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_system_audit_logs_org_created",
        "system_audit_logs",
        ["organization_id", "created_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_system_audit_logs_user_created",
        "system_audit_logs",
        ["user_id", "created_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_invoices_org_created",
        "invoices",
        ["organization_id", "created_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_production_logs_asset_timestamp",
        "production_logs",
        ["asset_id", "timestamp"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_inventory_org_sku",
        "inventory",
        ["organization_id", "sku_name"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_assets_org_status_enum",
        "assets",
        ["organization_id", "status_enum"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_compliance_cases_org_status",
        "compliance_cases",
        ["organization_id", "status"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_compliance_cases_org_created",
        "compliance_cases",
        ["organization_id", "created_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_comms_inbox_org_created",
        "comms_inbox",
        ["organization_id", "created_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_operational_expenses_org_created",
        "operational_expenses",
        ["organization_id", "created_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index("ix_users_created_at", "users", ["created_at"], unique=False, if_not_exists=True)
    op.create_index(
        "ix_user_org_memberships_org_user",
        "user_organization_memberships",
        ["organization_id", "user_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_health_logs_user_logged_on",
        "health_logs",
        ["user_id", "logged_on"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_personal_reminders_user_remind",
        "personal_reminders",
        ["user_id", "remind_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_enc_notes_user_created",
        "enc_notes",
        ["user_id", "created_at"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    raise NotImplementedError("0007 downgrade not implemented.")
