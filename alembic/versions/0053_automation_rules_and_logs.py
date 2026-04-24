"""Add automation rules and activity logs.

Revision ID: 0053_automation_rules_and_logs
Revises: 0052_mission_planning_tables
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0053_automation_rules_and_logs"
down_revision: Union[str, Sequence[str], None] = "0052_mission_planning_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("automation_rules"):
        op.create_table(
            "automation_rules",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("trigger_type", sa.String(length=64), nullable=False),
            sa.Column("condition_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("action_type", sa.String(length=64), nullable=False),
            sa.Column("action_config_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_automation_rules_user_id", "automation_rules", ["user_id"], unique=False)
        op.create_index("ix_automation_rules_user_enabled", "automation_rules", ["user_id", "enabled"], unique=False)

    if not insp.has_table("automation_logs"):
        op.create_table(
            "automation_logs",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("rule_id", sa.BigInteger(), sa.ForeignKey("automation_rules.id", ondelete="SET NULL"), nullable=True),
            sa.Column("trigger_type", sa.String(length=64), nullable=False),
            sa.Column("event_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("action_taken", sa.String(length=64), nullable=False),
            sa.Column("action_result_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_automation_logs_user_id", "automation_logs", ["user_id"], unique=False)
        op.create_index("ix_automation_logs_rule_id", "automation_logs", ["rule_id"], unique=False)
        op.create_index("ix_automation_logs_user_created", "automation_logs", ["user_id", "created_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table("automation_logs"):
        op.drop_index("ix_automation_logs_user_created", table_name="automation_logs", if_exists=True)
        op.drop_index("ix_automation_logs_rule_id", table_name="automation_logs", if_exists=True)
        op.drop_index("ix_automation_logs_user_id", table_name="automation_logs", if_exists=True)
        op.drop_table("automation_logs")

    if insp.has_table("automation_rules"):
        op.drop_index("ix_automation_rules_user_enabled", table_name="automation_rules", if_exists=True)
        op.drop_index("ix_automation_rules_user_id", table_name="automation_rules", if_exists=True)
        op.drop_table("automation_rules")
