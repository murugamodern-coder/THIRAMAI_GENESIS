"""Continuity goals, user settings, and link to action_execution_runs.

Revision ID: 0063_continuity_autonomous_engine
Revises: 0062_action_execution_layer
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0063_continuity_autonomous_engine"
down_revision: Union[str, Sequence[str], None] = "0062_action_execution_layer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("continuity_goals"):
        op.create_table(
            "continuity_goals",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("organization_id", sa.BigInteger(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("objective", sa.Text(), nullable=False),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
            sa.Column("progress_pct", sa.Float(), nullable=False, server_default="0"),
            sa.Column("steps_completed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_steps_est", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("remaining_actions_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("completed_steps_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("meta_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint(
                "status in ('active','paused','completed','cancelled','interrupted','waiting_action')",
                name="ck_continuity_goals_status",
            ),
        )
        op.create_index("ix_continuity_goals_user_status", "continuity_goals", ["user_id", "status"], unique=False)
        op.create_index("ix_continuity_goals_org", "continuity_goals", ["organization_id"], unique=False)

    if not insp.has_table("continuity_user_settings"):
        op.create_table(
            "continuity_user_settings",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("organization_id", sa.BigInteger(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("autonomy_level", sa.String(length=32), nullable=False, server_default="assist"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("time_budget_minutes_per_day", sa.Integer(), nullable=False, server_default="120"),
            sa.Column("capital_budget", sa.Float(), nullable=False, server_default="0"),
            sa.Column("effort_budget", sa.Integer(), nullable=False, server_default="10"),
            sa.Column("allow_auto_batch_medium", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("last_tick_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("runs_today", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("meta_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("user_id", "organization_id", name="uq_continuity_settings_user_org"),
        )
        op.create_index("ix_continuity_user_settings_user", "continuity_user_settings", ["user_id"], unique=False)

    insp2 = sa.inspect(bind)
    if insp2.has_table("action_execution_runs"):
        cols = [c.get("name") for c in insp2.get_columns("action_execution_runs")]
        if "continuity_goal_id" not in cols:
            op.add_column(
                "action_execution_runs",
                sa.Column("continuity_goal_id", sa.BigInteger(), nullable=True),
            )
            op.create_index("ix_action_execution_runs_continuity_goal", "action_execution_runs", ["continuity_goal_id"], unique=False)
            op.create_foreign_key(
                "fk_action_runs_continuity_goal",
                "action_execution_runs",
                "continuity_goals",
                ["continuity_goal_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table("action_execution_runs"):
        cols = [c.get("name") for c in insp.get_columns("action_execution_runs")]
        if "continuity_goal_id" in cols:
            op.drop_constraint("fk_action_runs_continuity_goal", "action_execution_runs", type_="foreignkey")
            op.drop_index("ix_action_execution_runs_continuity_goal", table_name="action_execution_runs", if_exists=True)
            op.drop_column("action_execution_runs", "continuity_goal_id")
    if insp.has_table("continuity_user_settings"):
        op.drop_table("continuity_user_settings")
    if insp.has_table("continuity_goals"):
        op.drop_table("continuity_goals")
