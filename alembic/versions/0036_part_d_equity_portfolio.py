"""Part D: equity paper portfolio + transaction history for stock assistant.

Revision ID: 0036_part_d_equity_portfolio
Revises: 0035_part_c_research_engine
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0036_part_d_equity_portfolio"
down_revision: Union[str, Sequence[str], None] = "0035_part_c_research_engine"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "equity_portfolio_positions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("exchange_suffix", sa.String(length=8), nullable=False, server_default="NS"),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("avg_buy_price_inr", sa.Numeric(18, 4), nullable=False, server_default="0"),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "symbol", "exchange_suffix", name="uq_equity_position_user_sym_ex"),
    )
    op.create_index("ix_equity_portfolio_positions_user", "equity_portfolio_positions", ["user_id"], unique=False)

    op.create_table(
        "equity_portfolio_transactions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("exchange_suffix", sa.String(length=8), nullable=False, server_default="NS"),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("price_inr", sa.Numeric(18, 4), nullable=False),
        sa.Column("fees_inr", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("realized_pnl_inr", sa.Numeric(18, 4), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_equity_tx_user_created", "equity_portfolio_transactions", ["user_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_equity_tx_user_created", table_name="equity_portfolio_transactions")
    op.drop_table("equity_portfolio_transactions")
    op.drop_index("ix_equity_portfolio_positions_user", table_name="equity_portfolio_positions")
    op.drop_table("equity_portfolio_positions")
