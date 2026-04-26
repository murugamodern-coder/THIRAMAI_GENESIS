"""Paper-trading simulator.

Uses real market prices (yfinance) but virtual capital so the strategy stack can
be exercised end-to-end without a broker connection or real money. Trade
intents are persisted to the ``paper_trades`` table for audit + analytics.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import text

from core.database import get_engine

logger = logging.getLogger(__name__)


class PaperTrader:
    """Virtual capital, real prices."""

    def __init__(self, initial_capital: float = 100_000.0, org_id: int = 1) -> None:
        self.initial_capital = float(initial_capital)
        self.org_id = int(org_id)
        self.capital = float(initial_capital)

    def get_live_price(self, symbol: str) -> float:
        """Return the latest close price via yfinance, ``0.0`` on any failure."""
        try:
            import yfinance as yf  # type: ignore[import-not-found]
        except ImportError:
            logger.warning("paper_trader_yfinance_missing")
            return 0.0
        try:
            yf_symbol = "^NSEI" if symbol.upper() == "NIFTY50" else (
                symbol if symbol.endswith(".NS") or symbol.startswith("^") else f"{symbol}.NS"
            )
            ticker = yf.Ticker(yf_symbol)
            hist = ticker.history(period="1d", interval="1d", auto_adjust=False)
            if hist is None or hist.empty:
                return 0.0
            return float(hist["Close"].iloc[-1])
        except Exception as exc:
            logger.error("price_fetch_error symbol=%s: %s", symbol, exc)
            return 0.0

    def place_paper_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        strategy_name: str = "rsi_macd",
    ) -> dict[str, Any]:
        """Persist a virtual ``open`` paper trade at the latest market price."""
        price = self.get_live_price(symbol)
        if price == 0.0:
            return {"ok": False, "error": "price_unavailable", "symbol": symbol}

        engine = get_engine()
        if engine is None:
            return {"ok": False, "error": "database_unavailable"}
        try:
            with engine.connect() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO paper_trades
                        (symbol, side, quantity, entry_price,
                         strategy_name, status, org_id, created_at)
                        VALUES
                        (:symbol, :side, :qty, :price,
                         :strategy, 'open', :org_id, NOW())
                        """
                    ),
                    {
                        "symbol": symbol,
                        "side": str(side).upper(),
                        "qty": int(quantity),
                        "price": float(price),
                        "strategy": strategy_name,
                        "org_id": self.org_id,
                    },
                )
                conn.commit()
        except Exception as exc:
            logger.error("paper_trade_error: %s", exc)
            return {"ok": False, "error": str(exc)}

        return {
            "ok": True,
            "symbol": symbol,
            "side": str(side).upper(),
            "quantity": int(quantity),
            "entry_price": float(price),
            "paper_trade": True,
            "strategy_name": strategy_name,
        }

    def close_paper_order(self, trade_id: int, exit_price: float | None = None) -> dict[str, Any]:
        """Close an open paper trade and record realised PnL."""
        engine = get_engine()
        if engine is None:
            return {"ok": False, "error": "database_unavailable"}
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        """
                        SELECT symbol, side, quantity, entry_price
                        FROM paper_trades WHERE id = :tid AND status = 'open'
                        """
                    ),
                    {"tid": int(trade_id)},
                ).fetchone()
                if not row:
                    return {"ok": False, "error": "trade_not_found_or_closed", "trade_id": trade_id}
                symbol, side, qty, entry_price = row[0], row[1], int(row[2] or 0), float(row[3] or 0)
                price = float(exit_price) if exit_price is not None else self.get_live_price(symbol)
                direction = 1.0 if str(side).upper() == "BUY" else -1.0
                realized = (price - entry_price) * qty * direction
                conn.execute(
                    text(
                        """
                        UPDATE paper_trades
                        SET exit_price = :price,
                            realized_pnl = :pnl,
                            status = 'closed',
                            closed_at = NOW()
                        WHERE id = :tid
                        """
                    ),
                    {"price": price, "pnl": realized, "tid": int(trade_id)},
                )
                conn.commit()
            return {"ok": True, "trade_id": int(trade_id), "exit_price": price, "realized_pnl": realized}
        except Exception as exc:
            logger.error("paper_close_error: %s", exc)
            return {"ok": False, "error": str(exc)}

    def get_open_positions(self) -> list[dict[str, Any]]:
        """List open paper positions with mark-to-market PnL."""
        engine = get_engine()
        if engine is None:
            return []
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT id, symbol, side, quantity,
                               entry_price, strategy_name, created_at
                        FROM paper_trades
                        WHERE status = 'open'
                          AND org_id = :org_id
                        ORDER BY created_at DESC
                        """
                    ),
                    {"org_id": self.org_id},
                ).fetchall()
        except Exception as exc:
            logger.error("positions_error: %s", exc)
            return []

        positions: list[dict[str, Any]] = []
        for r in rows:
            entry_price = float(r[4] or 0)
            current_price = self.get_live_price(r[1])
            direction = 1.0 if str(r[2]).upper() == "BUY" else -1.0
            pnl = (current_price - entry_price) * int(r[3] or 0) * direction
            pnl_pct = (current_price - entry_price) / entry_price if entry_price > 0 else 0.0
            positions.append(
                {
                    "id": int(r[0]),
                    "symbol": r[1],
                    "side": r[2],
                    "quantity": int(r[3] or 0),
                    "entry_price": entry_price,
                    "current_price": float(current_price),
                    "unrealized_pnl": round(pnl, 2),
                    "pnl_pct": f"{pnl_pct:.2%}",
                    "strategy": r[5],
                    "opened_at": str(r[6]),
                }
            )
        return positions

    def get_paper_pnl_summary(self) -> dict[str, Any]:
        """Aggregate realised PnL across closed paper trades."""
        engine = get_engine()
        if engine is None:
            return {"ok": False, "error": "database_unavailable"}
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        """
                        SELECT
                            COUNT(*) AS total_trades,
                            SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) AS wins,
                            SUM(CASE WHEN realized_pnl <= 0 THEN 1 ELSE 0 END) AS losses,
                            COALESCE(SUM(realized_pnl), 0) AS total_pnl,
                            COALESCE(AVG(realized_pnl), 0) AS avg_pnl
                        FROM paper_trades
                        WHERE status = 'closed'
                          AND org_id = :org_id
                        """
                    ),
                    {"org_id": self.org_id},
                ).fetchone()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        total = int(row[0] or 0) if row else 0
        wins = int(row[1] or 0) if row else 0
        losses = int(row[2] or 0) if row else 0
        total_pnl = float(row[3] or 0) if row else 0.0
        avg_pnl = float(row[4] or 0) if row else 0.0
        return {
            "ok": True,
            "total_trades": total,
            "winning_trades": wins,
            "losing_trades": losses,
            "win_rate": f"{(wins / total) if total else 0:.1%}",
            "win_rate_value": (wins / total) if total else 0.0,
            "total_pnl": total_pnl,
            "avg_pnl_per_trade": avg_pnl,
            "paper_capital": self.initial_capital,
            "paper_mode": True,
        }

    def auto_run_strategy(self) -> dict[str, Any]:
        """Run the regime-best strategy on a small watchlist and place paper orders.

        Skips outside NSE market hours (09:15 – 15:30 IST, Monday–Friday).
        """
        if not self._is_market_open():
            return {"ok": True, "message": "market_closed"}

        try:
            from services.quant.ohlcv_store import get_ohlcv
            from services.quant.position_sizer import calculate_position_size
            from services.quant.strategy_registry import StrategyRegistry
        except Exception as exc:
            return {"ok": False, "error": f"quant_imports_failed: {exc}"}

        strategy = StrategyRegistry.get_best_for_regime("trending")
        watchlist = ["RELIANCE", "TCS", "INFY", "HDFCBANK"]
        orders_placed: list[dict[str, Any]] = []

        for symbol in watchlist:
            try:
                candles = get_ohlcv(symbol, "day", limit=50)
                if len(candles) < 30:
                    continue
                signal = strategy.entry_signal(list(reversed(candles)))
                if not signal:
                    continue
                current_price = self.get_live_price(symbol)
                if current_price <= 0:
                    continue
                sizing = calculate_position_size(self.capital, current_price, candles)
                order = self.place_paper_order(
                    symbol=symbol,
                    side=signal,
                    quantity=int(sizing.get("quantity") or 1),
                    strategy_name=strategy.name,
                )
                if order.get("ok"):
                    orders_placed.append(order)
            except Exception as exc:
                logger.error("auto_run_error symbol=%s: %s", symbol, exc)

        return {"ok": True, "orders_placed": len(orders_placed), "orders": orders_placed}

    def _is_market_open(self) -> bool:
        """Return ``True`` during NSE trading hours (Asia/Kolkata)."""
        try:
            try:
                from zoneinfo import ZoneInfo  # type: ignore[import-not-found]

                ist = ZoneInfo("Asia/Kolkata")
            except ImportError:
                import pytz  # type: ignore[import-not-found]

                ist = pytz.timezone("Asia/Kolkata")
            now = datetime.now(ist)
        except Exception:
            now = datetime.now()
        if now.weekday() >= 5:
            return False
        market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
        market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        return market_open <= now <= market_close
