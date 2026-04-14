"""Upgrade 2.2 — autonomous agent: goals, daily plans, action log, subtasks.

Revision ID: 0041_jarvis_autonomous_agent
Revises: 0040_jarvis_proactive_feedback
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0041_jarvis_autonomous_agent"
down_revision: Union[str, Sequence[str], None] = "0040_jarvis_proactive_feedback"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jarvis_goals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=True),
        sa.Column("goal_type", sa.String(length=64), nullable=False, server_default="custom"),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("target_value", sa.String(length=512), nullable=True),
        sa.Column("deadline", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("progress", sa.JSON(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jarvis_goals_user_status", "jarvis_goals", ["user_id", "status"], unique=False)

    op.create_table(
        "jarvis_goal_subtasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("goal_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["goal_id"], ["jarvis_goals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jarvis_goal_subtasks_goal", "jarvis_goal_subtasks", ["goal_id"], unique=False)

    op.create_table(
        "jarvis_daily_agent_plans",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("plan_date", sa.Date(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "plan_date", name="uq_jarvis_daily_agent_plan_user_date"),
    )
    op.create_index("ix_jarvis_daily_agent_plans_user", "jarvis_daily_agent_plans", ["user_id"], unique=False)

    op.create_table(
        "jarvis_agent_action_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("action_kind", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_jarvis_agent_action_log_user_created",
        "jarvis_agent_action_log",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_jarvis_agent_action_log_user_created", table_name="jarvis_agent_action_log")
    op.drop_table("jarvis_agent_action_log")
    op.drop_index("ix_jarvis_daily_agent_plans_user", table_name="jarvis_daily_agent_plans")
    op.drop_table("jarvis_daily_agent_plans")
    op.drop_index("ix_jarvis_goal_subtasks_goal", table_name="jarvis_goal_subtasks")
    op.drop_table("jarvis_goal_subtasks")
    op.drop_index("ix_jarvis_goals_user_status", table_name="jarvis_goals")
    op.drop_table("jarvis_goals")
