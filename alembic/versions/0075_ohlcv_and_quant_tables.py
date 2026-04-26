"""Add OHLCV store and quant strategy run tables.

Adds:
- ``ohlcv_data``     (historical candlestick store keyed by ``(symbol, interval, timestamp)``)
- ``strategy_runs``  (backtest / paper / live result snapshots)

Revision ID: 0075_ohlcv_and_quant_tables
Revises: 0074_self_evolution_phase4
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0075_ohlcv_and_quant_tables"
down_revision: Union[str, Sequence[str], None] = "0074_self_evolution_phase4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ohlcv_data (
            id BIGSERIAL PRIMARY KEY,
            symbol VARCHAR(50) NOT NULL,
            interval VARCHAR(20) NOT NULL,
            timestamp TIMESTAMPTZ NOT NULL,
            open DECIMAL(12,4) NOT NULL,
            high DECIMAL(12,4) NOT NULL,
            low DECIMAL(12,4) NOT NULL,
            close DECIMAL(12,4) NOT NULL,
            volume BIGINT NOT NULL DEFAULT 0,
            org_id BIGINT NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(symbol, interval, timestamp)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_interval_ts
        ON ohlcv_data(symbol, interval, timestamp DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_runs (
            id BIGSERIAL PRIMARY KEY,
            strategy_name VARCHAR(100) NOT NULL,
            symbol VARCHAR(50) NOT NULL,
            run_type VARCHAR(20) NOT NULL DEFAULT 'backtest',
            total_trades INT DEFAULT 0,
            win_rate DECIMAL(5,4) DEFAULT 0,
            total_pnl DECIMAL(12,2) DEFAULT 0,
            sharpe_ratio DECIMAL(8,4) DEFAULT 0,
            max_drawdown DECIMAL(5,4) DEFAULT 0,
            org_id BIGINT NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_strategy_runs_strategy_symbol
        ON strategy_runs(strategy_name, symbol, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_strategy_runs_strategy_symbol")
    op.execute("DROP TABLE IF EXISTS strategy_runs")
    op.execute("DROP INDEX IF EXISTS idx_ohlcv_symbol_interval_ts")
    op.execute("DROP TABLE IF EXISTS ohlcv_data")
