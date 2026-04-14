"""Upgrade 4 — persisted stock price / percent alerts for realtime monitor.

Revision ID: 0043_stock_price_alerts
Revises: 0042_jarvis_agent_event_queue
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0043_stock_price_alerts"
down_revision: Union[str, Sequence[str], None] = "0042_jarvis_agent_event_queue"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stock_price_alerts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("exchange_suffix", sa.String(length=8), nullable=False, server_default="NS"),
        sa.Column("condition_type", sa.String(length=24), nullable=False),
        sa.Column("price_threshold", sa.Numeric(18, 4), nullable=True),
        sa.Column("reference_price", sa.Numeric(18, 4), nullable=True),
        sa.Column("percent_threshold", sa.Numeric(10, 4), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False, server_default="notify"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stock_price_alerts_user_active", "stock_price_alerts", ["user_id", "is_active"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_stock_price_alerts_user_active", table_name="stock_price_alerts")
    op.drop_table("stock_price_alerts")
