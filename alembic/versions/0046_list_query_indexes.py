"""Composite indexes for tenant-scoped list queries (usage + inventory).

Revision ID: 0046_list_query_indexes
Revises: 0045_user_product_profile
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0046_list_query_indexes"
down_revision: Union[str, Sequence[str], None] = "0045_user_product_profile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_usage_logs_org_created",
        "usage_logs",
        ["org_id", "created_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_inventory_items_org_created",
        "inventory_items",
        ["organization_id", "created_at"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_inventory_items_org_created", table_name="inventory_items")
    op.drop_index("ix_usage_logs_org_created", table_name="usage_logs")
