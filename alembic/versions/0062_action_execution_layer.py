"""Action execution layer: runs, steps, execution memory.

Revision ID: 0062_action_execution_layer
Revises: 0061_research_projects_table
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0062_action_execution_layer"
down_revision: Union[str, Sequence[str], None] = "0061_research_projects_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("action_execution_runs"):
        op.create_table(
            "action_execution_runs",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("organization_id", sa.BigInteger(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_command", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="planned"),
            sa.Column("meta_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint(
                "status in ('planned','awaiting_confirmation','running','completed','failed','cancelled')",
                name="ck_action_execution_runs_status",
            ),
        )
        op.create_index("ix_action_execution_runs_user_created", "action_execution_runs", ["user_id", "created_at"], unique=False)
        op.create_index("ix_action_execution_runs_user_status", "action_execution_runs", ["user_id", "status"], unique=False)

    if not insp.has_table("action_execution_steps"):
        op.create_table(
            "action_execution_steps",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("run_id", sa.BigInteger(), sa.ForeignKey("action_execution_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("step_order", sa.Integer(), nullable=False),
            sa.Column("phase", sa.String(length=16), nullable=False),
            sa.Column("step_kind", sa.String(length=64), nullable=False),
            sa.Column("risk_level", sa.String(length=16), nullable=False, server_default="medium"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("result_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("explicit_confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint(
                "phase in ('search','analyze','decide','act')",
                name="ck_action_execution_steps_phase",
            ),
            sa.CheckConstraint(
                "risk_level in ('low','medium','high')",
                name="ck_action_execution_steps_risk_level",
            ),
            sa.CheckConstraint(
                "status in ('pending','awaiting_confirmation','blocked','running','done','failed','skipped')",
                name="ck_action_execution_steps_status",
            ),
        )
        op.create_index("ix_action_execution_steps_run_order", "action_execution_steps", ["run_id", "step_order"], unique=False)

    if not insp.has_table("execution_memory_entries"):
        op.create_table(
            "execution_memory_entries",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("organization_id", sa.BigInteger(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("fingerprint", sa.String(length=128), nullable=False),
            sa.Column("step_kind", sa.String(length=64), nullable=False),
            sa.Column("success", sa.Boolean(), nullable=False),
            sa.Column("summary", sa.String(length=512), nullable=False, server_default=""),
            sa.Column("detail_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_execution_memory_user_fp", "execution_memory_entries", ["user_id", "fingerprint"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table("execution_memory_entries"):
        op.drop_index("ix_execution_memory_user_fp", table_name="execution_memory_entries", if_exists=True)
        op.drop_table("execution_memory_entries")
    if insp.has_table("action_execution_steps"):
        op.drop_index("ix_action_execution_steps_run_order", table_name="action_execution_steps", if_exists=True)
        op.drop_table("action_execution_steps")
    if insp.has_table("action_execution_runs"):
        op.drop_index("ix_action_execution_runs_user_status", table_name="action_execution_runs", if_exists=True)
        op.drop_index("ix_action_execution_runs_user_created", table_name="action_execution_runs", if_exists=True)
        op.drop_table("action_execution_runs")
