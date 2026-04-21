"""Persist agentic workflow tasks (Trading OS Jarvis).

Revision ID: 0048_agent_tasks
Revises: 0047_add_rls_tenant_isolation
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0048_agent_tasks"
down_revision: Union[str, Sequence[str], None] = "0047_add_rls_tenant_isolation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("os_key", sa.String(length=32), nullable=False),
        sa.Column("full_plan_json", sa.JSON(), nullable=False),
        sa.Column("current_step_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "execution_logs",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uq_agent_tasks_task_id"),
    )
    op.create_index("ix_agent_tasks_organization_id", "agent_tasks", ["organization_id"], unique=False)
    op.create_index("ix_agent_tasks_user_id", "agent_tasks", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_agent_tasks_user_id", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_organization_id", table_name="agent_tasks")
    op.drop_table("agent_tasks")
