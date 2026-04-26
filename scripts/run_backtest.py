"""Run a real backtest on yfinance-seeded OHLCV data.

Generates proof of strategy performance:
1. Seeds the top NSE symbols into ``ohlcv_data`` (yfinance fallback when Kite is offline).
2. Runs the RSI+MACD strategy across a watchlist with INR 100k of virtual capital.
3. Persists the per-symbol metrics into ``strategy_runs`` for the dashboard.
4. Prints a summary verdict.

Use:
    python scripts/run_backtest.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

from sqlalchemy import text  # noqa: E402

from core.database import get_engine  # noqa: E402
from services.quant.backtester import RSIMACDStrategy, run_backtest  # noqa: E402
from services.quant.ohlcv_store import fetch_default_symbols_yfinance, get_ohlcv  # noqa: E402


WATCHLIST = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]


def run_and_save_backtest() -> dict[str, Any]:
    print("=== THIRAMAI BACKTEST ENGINE ===")

    print("\n1. Seeding OHLCV data from Yahoo Finance...")
    seed_result = fetch_default_symbols_yfinance()
    print(
        f"   Seeded {seed_result['total']} symbols "
        f"(stored {seed_result.get('stored_total', 0)} candles total)"
    )

    print("\n2. Running RSI-MACD backtest...")
    strategy = RSIMACDStrategy()
    results = []
    for symbol in WATCHLIST:
        candles = get_ohlcv(symbol, "day", limit=365)
        if len(candles) < 50:
            print(f"   {symbol}: insufficient data ({len(candles)} candles)")
            continue
        result = run_backtest(strategy, symbol, initial_capital=100_000.0)
        results.append(result)
        print(f"   {symbol}:")
        print(f"     Trades: {result.total_trades}")
        print(f"     Win rate: {result.win_rate:.1%}")
        print(f"     Total PnL: INR {result.total_pnl:,.0f}")
        print(f"     Sharpe: {result.sharpe_ratio:.2f}")
        print(f"     Max DD: {result.max_drawdown:.1%}")

    if not results:
        print("\nNo symbols produced enough data for a backtest.")
        return {"ok": False, "error": "no_results"}

    print("\n3. Saving results to strategy_runs...")
    engine = get_engine()
    if engine is not None:
        with engine.connect() as conn:
            for r in results:
                conn.execute(
                    text(
                        """
                        INSERT INTO strategy_runs
                        (strategy_name, symbol, run_type,
                         total_trades, win_rate, total_pnl,
                         sharpe_ratio, max_drawdown, org_id)
                        VALUES
                        (:sname, :sym, 'backtest',
                         :trades, :wr, :pnl, :sharpe, :dd, 1)
                        """
                    ),
                    {
                        "sname": r.strategy_name,
                        "sym": r.symbol,
                        "trades": r.total_trades,
                        "wr": float(r.win_rate),
                        "pnl": float(r.total_pnl),
                        "sharpe": float(r.sharpe_ratio),
                        "dd": float(r.max_drawdown),
                    },
                )
            conn.commit()
    else:
        print("   (database unavailable — results not persisted)")

    print("\n=== BACKTEST SUMMARY ===")
    avg_wr = sum(r.win_rate for r in results) / len(results)
    total_pnl = sum(r.total_pnl for r in results)
    avg_sharpe = sum(r.sharpe_ratio for r in results) / len(results)

    print(f"Symbols tested: {len(results)}")
    print(f"Avg win rate: {avg_wr:.1%}")
    print(f"Total PnL: INR {total_pnl:,.0f}")
    print(f"Avg Sharpe: {avg_sharpe:.2f}")

    verdict = "PROMISING" if avg_sharpe > 0.5 else "NEEDS_IMPROVEMENT"
    print(f"Verdict: {verdict}")

    return {
        "ok": True,
        "symbols_tested": len(results),
        "avg_win_rate": round(avg_wr, 4),
        "total_pnl": round(total_pnl, 2),
        "avg_sharpe": round(avg_sharpe, 4),
        "verdict": verdict,
    }


if __name__ == "__main__":
    result = run_and_save_backtest()
    print(f"\nFinal: {json.dumps(result, indent=2)}")
