"""Add explainability fields to execution audit logs.

Revision ID: 0059_execution_audit_reasoning_fields
Revises: 0058_money_loop_config
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0059_execution_audit_reasoning_fields"
down_revision: Union[str, Sequence[str], None] = "0058_money_loop_config"
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
    if not insp.has_table("execution_audit_logs"):
        return
    if not _has_column(insp, "execution_audit_logs", "execution_id"):
        op.add_column("execution_audit_logs", sa.Column("execution_id", sa.String(length=120), nullable=True))
        op.create_index("ix_execution_audit_logs_execution_id", "execution_audit_logs", ["execution_id"], unique=False)
    if not _has_column(insp, "execution_audit_logs", "reasoning_summary"):
        op.add_column("execution_audit_logs", sa.Column("reasoning_summary", sa.Text(), nullable=True))
    if not _has_column(insp, "execution_audit_logs", "why_action_taken"):
        op.add_column("execution_audit_logs", sa.Column("why_action_taken", sa.Text(), nullable=True))
    if not _has_column(insp, "execution_audit_logs", "data_influenced_json"):
        op.add_column(
            "execution_audit_logs",
            sa.Column("data_influenced_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("execution_audit_logs"):
        return
    if _has_column(insp, "execution_audit_logs", "data_influenced_json"):
        op.drop_column("execution_audit_logs", "data_influenced_json")
    if _has_column(insp, "execution_audit_logs", "why_action_taken"):
        op.drop_column("execution_audit_logs", "why_action_taken")
    if _has_column(insp, "execution_audit_logs", "reasoning_summary"):
        op.drop_column("execution_audit_logs", "reasoning_summary")
    if _has_column(insp, "execution_audit_logs", "execution_id"):
        op.drop_index("ix_execution_audit_logs_execution_id", table_name="execution_audit_logs", if_exists=True)
        op.drop_column("execution_audit_logs", "execution_id")
