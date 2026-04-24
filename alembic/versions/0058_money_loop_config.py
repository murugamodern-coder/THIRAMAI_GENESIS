"""Add money loop config table.

Revision ID: 0058_money_loop_config
Revises: 0057_governance_guardrails_and_audit
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0058_money_loop_config"
down_revision: Union[str, Sequence[str], None] = "0057_governance_guardrails_and_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table("money_loop_config"):
        return
    op.create_table(
        "money_loop_config",
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("max_daily_capital", sa.Float(), nullable=False, server_default="50000"),
        sa.Column("max_parallel_missions", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("risk_level", sa.String(length=32), nullable=False, server_default="medium"),
        sa.Column("auto_execute", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table("money_loop_config"):
        op.drop_table("money_loop_config")
