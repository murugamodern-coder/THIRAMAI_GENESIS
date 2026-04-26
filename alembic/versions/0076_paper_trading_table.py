"""Add paper_trades table for the paper-trading simulator.

Revision ID: 0076_paper_trading_table
Revises: 0075_ohlcv_and_quant_tables
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0076_paper_trading_table"
down_revision: Union[str, Sequence[str], None] = "0075_ohlcv_and_quant_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_trades (
            id BIGSERIAL PRIMARY KEY,
            symbol VARCHAR(50) NOT NULL,
            side VARCHAR(10) NOT NULL,
            quantity INT NOT NULL DEFAULT 1,
            entry_price DECIMAL(12,4) NOT NULL DEFAULT 0,
            exit_price DECIMAL(12,4),
            realized_pnl DECIMAL(12,2),
            strategy_name VARCHAR(100),
            status VARCHAR(20) NOT NULL DEFAULT 'open',
            org_id BIGINT NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            closed_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_paper_trades_org_status
        ON paper_trades(org_id, status, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_paper_trades_org_status")
    op.execute("DROP TABLE IF EXISTS paper_trades")
