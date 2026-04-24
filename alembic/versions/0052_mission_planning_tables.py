"""Add mission planning tables.

Revision ID: 0052_mission_planning_tables
Revises: 0051_execute_conversation_memory
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0052_mission_planning_tables"
down_revision: Union[str, Sequence[str], None] = "0051_execute_conversation_memory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("missions"):
        op.create_table(
            "missions",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("title", sa.String(length=300), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="planned"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("status in ('planned','running','completed')", name="ck_missions_status"),
        )
        op.create_index("ix_missions_user_id", "missions", ["user_id"], unique=False)
        op.create_index("ix_missions_user_created", "missions", ["user_id", "created_at"], unique=False)

    if not insp.has_table("mission_steps"):
        op.create_table(
            "mission_steps",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("mission_id", sa.BigInteger(), sa.ForeignKey("missions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("step_order", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=300), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("result", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("status in ('pending','running','done','failed')", name="ck_mission_steps_status"),
        )
        op.create_index("ix_mission_steps_mission_id", "mission_steps", ["mission_id"], unique=False)
        op.create_index(
            "ix_mission_steps_mission_order",
            "mission_steps",
            ["mission_id", "step_order"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table("mission_steps"):
        op.drop_index("ix_mission_steps_mission_order", table_name="mission_steps", if_exists=True)
        op.drop_index("ix_mission_steps_mission_id", table_name="mission_steps", if_exists=True)
        op.drop_table("mission_steps")

    if insp.has_table("missions"):
        op.drop_index("ix_missions_user_created", table_name="missions", if_exists=True)
        op.drop_index("ix_missions_user_id", table_name="missions", if_exists=True)
        op.drop_table("missions")
