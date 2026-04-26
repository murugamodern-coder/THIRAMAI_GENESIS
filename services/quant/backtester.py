"""Strategy backtesting engine.

Runs any :class:`StrategyBase` subclass on historical OHLCV data from
:mod:`services.quant.ohlcv_store` and reports Sharpe ratio, drawdown,
win rate, and PnL.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

from services.quant.ohlcv_store import get_ohlcv

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    symbol: str
    entry_price: float
    exit_price: float
    entry_date: str
    exit_date: str
    side: str
    quantity: int
    pnl: float
    pnl_pct: float


@dataclass
class BacktestResult:
    strategy_name: str
    symbol: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    total_pnl_pct: float
    max_drawdown: float
    sharpe_ratio: float
    avg_trade_pnl: float
    trades: list[Trade]


class StrategyBase:
    """Base class for all strategies."""

    name = "base"

    def entry_signal(self, candles: list[dict]) -> Optional[str]:
        """Return ``"BUY"``, ``"SELL"``, or ``None``."""
        raise NotImplementedError

    def exit_signal(self, candles: list[dict], position: dict) -> bool:
        """Return ``True`` to exit the open position."""
        raise NotImplementedError

    def position_size(self, price: float, capital: float) -> int:
        """Default sizing: 10% of capital, minimum 1 share."""
        if price <= 0:
            return 1
        return max(1, int(capital * 0.10 / price))


class RSIMACDStrategy(StrategyBase):
    """Classic RSI + MACD momentum strategy."""

    name = "rsi_macd"

    def _rsi(self, prices: list[float], period: int = 14) -> float:
        if len(prices) < period + 1:
            return 50.0
        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        gains = [d for d in deltas if d > 0]
        losses = [-d for d in deltas if d < 0]
        avg_gain = sum(gains[-period:]) / period if gains else 0.0
        avg_loss = sum(losses[-period:]) / period if losses else 1.0
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _ema(self, prices: list[float], period: int) -> float:
        if not prices:
            return 0.0
        if len(prices) < period:
            return prices[-1]
        k = 2 / (period + 1)
        ema = prices[0]
        for price in prices[1:]:
            ema = price * k + ema * (1 - k)
        return ema

    def entry_signal(self, candles: list[dict]) -> Optional[str]:
        if len(candles) < 30:
            return None
        closes = [c["close"] for c in candles]
        rsi = self._rsi(closes)
        macd = self._ema(closes, 12) - self._ema(closes, 26)
        if rsi < 35 and macd > 0:
            return "BUY"
        if rsi > 65 and macd < 0:
            return "SELL"
        return None

    def exit_signal(self, candles: list[dict], position: dict) -> bool:
        current_price = candles[-1]["close"]
        entry_price = position["entry_price"]
        if entry_price <= 0:
            return False
        pnl_pct = (current_price - entry_price) / entry_price
        return pnl_pct >= 0.025 or pnl_pct <= -0.015


def _empty_result(strategy_name: str, symbol: str) -> BacktestResult:
    return BacktestResult(
        strategy_name=strategy_name,
        symbol=symbol,
        total_trades=0,
        winning_trades=0,
        losing_trades=0,
        win_rate=0.0,
        total_pnl=0.0,
        total_pnl_pct=0.0,
        max_drawdown=0.0,
        sharpe_ratio=0.0,
        avg_trade_pnl=0.0,
        trades=[],
    )


def run_backtest(
    strategy: StrategyBase,
    symbol: str,
    initial_capital: float = 100000.0,
    interval: str = "day",
) -> BacktestResult:
    """Run ``strategy`` against the most recent 500 candles for ``symbol``."""
    candles = get_ohlcv(symbol, interval, limit=500)
    if len(candles) < 50:
        logger.warning("backtest_insufficient_data symbol=%s have=%d", symbol, len(candles))
        return _empty_result(strategy.name, symbol)

    candles = list(reversed(candles))  # oldest first
    capital = initial_capital
    position: Optional[dict[str, Any]] = None
    trades: list[Trade] = []
    equity_curve: list[float] = [capital]

    for i in range(30, len(candles)):
        window = candles[: i + 1]
        current = candles[i]

        if position is None:
            signal = strategy.entry_signal(window)
            if signal == "BUY":
                qty = strategy.position_size(current["close"], capital)
                position = {
                    "entry_price": current["close"],
                    "entry_date": current["timestamp"],
                    "side": "BUY",
                    "qty": qty,
                }
            continue

        if strategy.exit_signal(window, position):
            exit_price = current["close"]
            entry_price = position["entry_price"]
            qty = position["qty"]
            pnl = (exit_price - entry_price) * qty
            pnl_pct = (exit_price - entry_price) / entry_price if entry_price else 0.0

            trades.append(
                Trade(
                    symbol=symbol,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    entry_date=position["entry_date"],
                    exit_date=current["timestamp"],
                    side=position["side"],
                    quantity=qty,
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                )
            )
            capital += pnl
            equity_curve.append(capital)
            position = None

    if not trades:
        return _empty_result(strategy.name, symbol)

    winning = [t for t in trades if t.pnl > 0]
    losing = [t for t in trades if t.pnl <= 0]
    total_pnl = sum(t.pnl for t in trades)

    returns = [t.pnl_pct for t in trades]
    avg_return = float(np.mean(returns)) if returns else 0.0
    std_return = float(np.std(returns)) if len(returns) > 1 else 1.0
    sharpe = (avg_return / std_return) * float(np.sqrt(252)) if std_return > 0 else 0.0

    peak = initial_capital
    max_dd = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    return BacktestResult(
        strategy_name=strategy.name,
        symbol=symbol,
        total_trades=len(trades),
        winning_trades=len(winning),
        losing_trades=len(losing),
        win_rate=len(winning) / len(trades),
        total_pnl=total_pnl,
        total_pnl_pct=total_pnl / initial_capital if initial_capital else 0.0,
        max_drawdown=max_dd,
        sharpe_ratio=sharpe,
        avg_trade_pnl=total_pnl / len(trades),
        trades=trades,
    )


def run_backtest_summary(symbol: str = "RELIANCE") -> dict[str, Any]:
    """Quick backtest with the built-in RSI+MACD strategy (returns plain dict)."""
    strategy = RSIMACDStrategy()
    result = run_backtest(strategy, symbol)
    return {
        "ok": True,
        "strategy": result.strategy_name,
        "symbol": result.symbol,
        "total_trades": result.total_trades,
        "win_rate": f"{result.win_rate:.1%}",
        "total_pnl": result.total_pnl,
        "sharpe_ratio": f"{result.sharpe_ratio:.2f}",
        "max_drawdown": f"{result.max_drawdown:.1%}",
        "verdict": "promising" if result.sharpe_ratio > 1.0 else "needs_improvement",
    }
