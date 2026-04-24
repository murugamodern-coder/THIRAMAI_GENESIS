"""Strategy experiments: hypothesis, execution, result, link to learning.

Revision ID: 0066_strategy_experiments_table
Revises: 0065_decision_intelligence
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0066_strategy_experiments_table"
down_revision: Union[str, Sequence[str], None] = "0065_decision_intelligence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("strategy_experiments"):
        return
    op.create_table(
        "strategy_experiments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "organization_id",
            sa.BigInteger(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("strategy_id", sa.String(160), nullable=False, server_default=""),
        sa.Column("experiment_group", sa.String(64), nullable=False, server_default="default"),
        sa.Column("strategy_snapshot_json", sa.JSON().with_variant(sa.dialects.postgresql.JSONB, "postgresql"), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("hypothesis", sa.Text(), nullable=False, server_default=""),
        sa.Column("execution_json", sa.JSON().with_variant(sa.dialects.postgresql.JSONB, "postgresql"), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("result_json", sa.JSON().with_variant(sa.dialects.postgresql.JSONB, "postgresql"), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("success", sa.Boolean(), nullable=True),
        sa.Column(
            "learning_log_id",
            sa.BigInteger(),
            sa.ForeignKey("learning_logs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_strategy_experiments_user_status", "strategy_experiments", ["user_id", "status"])
    op.create_index(
        "ix_strategy_experiments_user_group_created",
        "strategy_experiments",
        ["user_id", "experiment_group", "created_at"],
    )
    op.create_index("ix_strategy_experiments_learning_log", "strategy_experiments", ["learning_log_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("strategy_experiments"):
        op.drop_table("strategy_experiments")
