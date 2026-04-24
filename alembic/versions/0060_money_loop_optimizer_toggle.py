"""Add optimizer toggle to money loop config.

Revision ID: 0060_money_loop_optimizer_toggle
Revises: 0059_execution_audit_reasoning_fields
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0060_money_loop_optimizer_toggle"
down_revision: Union[str, Sequence[str], None] = "0059_execution_audit_reasoning_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(insp, table_name: str, column_name: str) -> bool:
    try:
        cols = insp.get_columns(table_name)
    except Exception:
        return False
    return any(str(c.get("name")) == column_name for c in cols)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("money_loop_config"):
        return
    if not _has_column(insp, "money_loop_config", "optimizer_enabled"):
        op.add_column(
            "money_loop_config",
            sa.Column("optimizer_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("money_loop_config"):
        return
    if _has_column(insp, "money_loop_config", "optimizer_enabled"):
        op.drop_column("money_loop_config", "optimizer_enabled")
