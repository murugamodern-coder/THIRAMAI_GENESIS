"""RSI + MACD momentum strategy (pandas-DataFrame edition).

This is the new pandas-based version of the classic RSI/MACD signal. The
legacy candle-list implementation in :mod:`services.quant.backtester` is
*kept untouched* so existing ``run_backtest`` / :class:`StrategyRegistry`
callers continue to work; this implementation is wired into the new
:class:`StrategyManager` / :class:`StrategySelector`.

Entry rule
----------

Long when RSI(14) crosses up through ``rsi_oversold`` AND the MACD line is
above the signal line. Both indicators must agree.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from services.quant.strategies.base import StrategyBase, StrategySignal


class RSIMACDStrategy(StrategyBase):
    """Best for trending markets, especially bullish reversals."""

    default_position_pct = 0.10

    def generate_signal(self, data: pd.DataFrame) -> StrategySignal:
        rsi_period = int(self.params.get("rsi_period", 14))
        rsi_oversold = float(self.params.get("rsi_oversold", 30.0))
        rsi_overbought = float(self.params.get("rsi_overbought", 70.0))
        macd_fast = int(self.params.get("macd_fast", 12))
        macd_slow = int(self.params.get("macd_slow", 26))
        macd_signal = int(self.params.get("macd_signal", 9))
        profit_pct = float(self.params.get("profit_pct", 0.04))
        stop_pct = float(self.params.get("stop_pct", 0.02))

        required = max(rsi_period, macd_slow + macd_signal) + 1
        if len(data) < required or "close" not in data.columns:
            return self._hold_signal(reasoning="insufficient data")

        close = data["close"].astype(float)
        rsi = self._rsi(close, rsi_period)
        macd_line, signal_line = self._macd(close, macd_fast, macd_slow, macd_signal)

        current = float(close.iloc[-1])
        if current <= 0:
            return self._hold_signal(reasoning="invalid price")

        macd_above_signal = macd_line > signal_line
        if rsi < rsi_oversold and macd_above_signal:
            return StrategySignal(
                action="buy",
                confidence=0.78,
                price_target=current * (1.0 + profit_pct),
                stop_loss=current * (1.0 - stop_pct),
                quantity=self._calculate_quantity(current),
                reasoning=f"RSI oversold ({rsi:.0f}) + MACD bullish",
            )
        if rsi > rsi_overbought and not macd_above_signal:
            return StrategySignal(
                action="sell",
                confidence=0.72,
                price_target=current * (1.0 - profit_pct),
                stop_loss=current * (1.0 + stop_pct),
                quantity=self._calculate_quantity(current),
                reasoning=f"RSI overbought ({rsi:.0f}) + MACD bearish",
            )
        return self._hold_signal(reasoning=f"no setup (RSI={rsi:.0f}, MACD signal={'+' if macd_above_signal else '-'})")

    def suitable_for_regime(self, regime: str) -> float:
        return {
            "trending_up": 0.85,
            "trending_down": 0.6,
            "ranging": 0.4,
            "volatile": 0.45,
        }.get(regime, 0.5)

    @staticmethod
    def _rsi(close: pd.Series, period: int) -> float:
        if len(close) < period + 1:
            return 50.0
        delta = close.diff().dropna()
        gains = delta.clip(lower=0.0)
        losses = -delta.clip(upper=0.0)
        avg_gain = float(gains.tail(period).mean())
        avg_loss = float(losses.tail(period).mean())
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return float(rsi) if np.isfinite(rsi) else 50.0

    @staticmethod
    def _macd(
        close: pd.Series, fast: int, slow: int, signal: int
    ) -> tuple[float, float]:
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        return float(macd_line.iloc[-1]), float(signal_line.iloc[-1])
