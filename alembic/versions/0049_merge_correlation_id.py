"""Merge 0048 heads and add correlation_id to agent_tasks for threading.

Revision ID: 0049_merge_correlation_id
Revises: 0048_agent_tasks, 0048_user_runtime_config
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0049_merge_correlation_id"
down_revision: Union[str, tuple[str, ...], None] = (
    "0048_agent_tasks",
    "0048_user_runtime_config",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if insp.has_table("agent_tasks"):
        cols = [c["name"] for c in insp.get_columns("agent_tasks")]
        if "correlation_id" not in cols:
            op.add_column(
                "agent_tasks",
                sa.Column("correlation_id", sa.String(length=128), nullable=True),
            )
            op.create_index(
                "ix_agent_tasks_correlation_id",
                "agent_tasks",
                ["correlation_id"],
                unique=False,
                if_not_exists=True,
            )


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if insp.has_table("agent_tasks"):
        cols = [c["name"] for c in insp.get_columns("agent_tasks")]
        if "correlation_id" in cols:
            op.drop_index("ix_agent_tasks_correlation_id", table_name="agent_tasks", if_exists=True)
            op.drop_column("agent_tasks", "correlation_id")
