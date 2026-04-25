"""Add tenant/time/status composite indexes (Week 1 performance pass).

Revision ID: 0070_add_performance_indexes
Revises: 0069_fix_learning_logs_user_id_integrity
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0070_add_performance_indexes"
down_revision: Union[str, Sequence[str], None] = "0069_fix_learning_logs_user_id_integrity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_index(insp, table: str, name: str) -> bool:
    try:
        for ix in insp.get_indexes(table):
            if str(ix.get("name")) == name:
                return True
    except Exception:
        pass
    return False


def upgrade() -> None:
    bind = op.get_bind()
    if bind is None:
        return
    insp = sa.inspect(bind)
    dialect = str(bind.dialect.name).lower()
    pg = dialect == "postgresql"

    # inventory_items: canonical table with created_at (legacy `inventory` has no created_at)
    if insp.has_table("inventory_items") and not _has_index(
        insp, "inventory_items", "idx_w1d1_inventory_items_org_created_desc"
    ):
        op.create_index(
            "idx_w1d1_inventory_items_org_created_desc",
            "inventory_items",
            ["organization_id", "created_at"],
            unique=False,
            if_not_exists=True,
            postgresql_ops={"created_at": "desc"} if pg else None,
        )

    if insp.has_table("invoices") and not _has_index(
        insp, "invoices", "idx_w1d1_invoices_org_created_desc"
    ):
        op.create_index(
            "idx_w1d1_invoices_org_created_desc",
            "invoices",
            ["organization_id", "created_at"],
            unique=False,
            if_not_exists=True,
            postgresql_ops={"created_at": "desc"} if pg else None,
        )

    if insp.has_table("conversations") and not _has_index(
        insp, "conversations", "idx_w1d1_conversations_user_created_desc"
    ):
        op.create_index(
            "idx_w1d1_conversations_user_created_desc",
            "conversations",
            ["user_id", "created_at"],
            unique=False,
            if_not_exists=True,
            postgresql_ops={"created_at": "desc"} if pg else None,
        )

    if insp.has_table("action_execution_runs") and not _has_index(
        insp, "action_execution_runs", "idx_w1d1_aer_org_status_created_desc"
    ):
        op.create_index(
            "idx_w1d1_aer_org_status_created_desc",
            "action_execution_runs",
            ["organization_id", "status", "created_at"],
            unique=False,
            if_not_exists=True,
            postgresql_ops={"created_at": "desc"} if pg else None,
        )

    # opportunities: no organization_id in schema — index (user_id, status)
    if insp.has_table("opportunities") and not _has_index(
        insp, "opportunities", "idx_w1d1_opportunities_user_status"
    ):
        op.create_index(
            "idx_w1d1_opportunities_user_status",
            "opportunities",
            ["user_id", "status"],
            unique=False,
            if_not_exists=True,
        )

    # automation_rules: no organization_id; prefer existing ix_automation_rules_user_enabled
    if (
        insp.has_table("automation_rules")
        and not _has_index(insp, "automation_rules", "idx_w1d1_automation_rules_user_enabled")
        and not _has_index(insp, "automation_rules", "ix_automation_rules_user_enabled")
    ):
        op.create_index(
            "idx_w1d1_automation_rules_user_enabled",
            "automation_rules",
            ["user_id", "enabled"],
            unique=False,
            if_not_exists=True,
        )

    # legacy inventory (no created_at): tenant filter only
    if insp.has_table("inventory") and not _has_index(insp, "inventory", "idx_w1d1_inventory_org"):
        op.create_index(
            "idx_w1d1_inventory_org",
            "inventory",
            ["organization_id"],
            unique=False,
            if_not_exists=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind is None:
        return
    insp = sa.inspect(bind)
    for table, name in [
        ("inventory", "idx_w1d1_inventory_org"),
        ("automation_rules", "idx_w1d1_automation_rules_user_enabled"),
        ("opportunities", "idx_w1d1_opportunities_user_status"),
        ("action_execution_runs", "idx_w1d1_aer_org_status_created_desc"),
        ("conversations", "idx_w1d1_conversations_user_created_desc"),
        ("invoices", "idx_w1d1_invoices_org_created_desc"),
        ("inventory_items", "idx_w1d1_inventory_items_org_created_desc"),
    ]:
        if insp.has_table(table) and _has_index(insp, table, name):
            op.drop_index(name, table_name=table, if_exists=True)
