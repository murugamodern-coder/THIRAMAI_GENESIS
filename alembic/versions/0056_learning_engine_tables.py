"""Add self-learning columns and strategy profiles.

Revision ID: 0056_learning_engine_tables
Revises: 0055_opportunities_engine_tables
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0056_learning_engine_tables"
down_revision: Union[str, Sequence[str], None] = "0055_opportunities_engine_tables"
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

    if insp.has_table("learning_logs"):
        if not _has_column(insp, "learning_logs", "user_id"):
            op.add_column("learning_logs", sa.Column("user_id", sa.BigInteger(), nullable=True))
            op.create_foreign_key(
                "fk_learning_logs_user_id_users",
                "learning_logs",
                "users",
                ["user_id"],
                ["id"],
                ondelete="SET NULL",
            )
            op.create_index("ix_learning_logs_user_id", "learning_logs", ["user_id"], unique=False)
        if not _has_column(insp, "learning_logs", "source_type"):
            op.add_column("learning_logs", sa.Column("source_type", sa.String(length=32), nullable=True))
        if not _has_column(insp, "learning_logs", "source_id"):
            op.add_column("learning_logs", sa.Column("source_id", sa.BigInteger(), nullable=True))
        if not _has_column(insp, "learning_logs", "input_data_json"):
            op.add_column("learning_logs", sa.Column("input_data_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        if not _has_column(insp, "learning_logs", "outcome_json"):
            op.add_column("learning_logs", sa.Column("outcome_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        if not _has_column(insp, "learning_logs", "success"):
            op.add_column("learning_logs", sa.Column("success", sa.Boolean(), nullable=True))

    if not insp.has_table("strategy_profiles"):
        op.create_table(
            "strategy_profiles",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("domain", sa.String(length=32), nullable=False),
            sa.Column("parameters_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("performance_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_strategy_profiles_user_id", "strategy_profiles", ["user_id"], unique=False)
        op.create_index("ix_strategy_profiles_user_domain", "strategy_profiles", ["user_id", "domain"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table("strategy_profiles"):
        op.drop_index("ix_strategy_profiles_user_domain", table_name="strategy_profiles", if_exists=True)
        op.drop_index("ix_strategy_profiles_user_id", table_name="strategy_profiles", if_exists=True)
        op.drop_table("strategy_profiles")
