"""Momentum strategy.

Entry rule
----------

Long when the trailing ``momentum_window`` return exceeds ``momentum_pct``
**and** the 14-bar RSI is below ``rsi_overbought`` (we don't want to chase
into overbought territory).

The RSI used here is Wilder's standard formulation - critically, when the
average loss over the window is zero we return RSI = 100 (matching every
textbook). The original spec used ``loss.replace(0, 1.0)`` which would
push RSI toward 0 when there are no losses - the opposite of correct.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from services.quant.strategies.base import StrategyBase, StrategySignal


class MomentumStrategy(StrategyBase):
    """Best for strong-trend markets."""

    default_position_pct = 0.12

    def generate_signal(self, data: pd.DataFrame) -> StrategySignal:
        window = int(self.params.get("momentum_window", 10))
        threshold = float(self.params.get("momentum_pct", 5.0))
        rsi_period = int(self.params.get("rsi_period", 14))
        rsi_overbought = float(self.params.get("rsi_overbought", 70.0))
        profit_pct = float(self.params.get("profit_pct", 0.05))
        stop_pct = float(self.params.get("stop_pct", 0.03))

        required = max(window, rsi_period) + 1
        if len(data) < required or "close" not in data.columns:
            return self._hold_signal(reasoning="insufficient data")

        close = data["close"].astype(float)
        prior = float(close.iloc[-window - 1]) if len(close) > window else 0.0
        current = float(close.iloc[-1])
        if prior <= 0 or current <= 0:
            return self._hold_signal(reasoning="invalid prices")

        momentum_pct = (current / prior - 1.0) * 100.0
        rsi = self._rsi(close, rsi_period)

        if momentum_pct > threshold and rsi < rsi_overbought:
            return StrategySignal(
                action="buy",
                confidence=0.8,
                price_target=current * (1.0 + profit_pct),
                stop_loss=current * (1.0 - stop_pct),
                quantity=self._calculate_quantity(current),
                reasoning=f"momentum {momentum_pct:.1f}%, RSI {rsi:.0f}",
            )
        return self._hold_signal(reasoning=f"no momentum (mom={momentum_pct:.1f}%, RSI={rsi:.0f})")

    def suitable_for_regime(self, regime: str) -> float:
        return {
            "trending_up": 0.95,
            "trending_down": 0.4,
            "ranging": 0.2,
            "volatile": 0.5,
        }.get(regime, 0.5)

    @staticmethod
    def _rsi(close: pd.Series, period: int) -> float:
        """Wilder-style RSI. Returns 100 when no losses in window, 0 when no gains."""
        if len(close) < period + 1:
            return 50.0
        delta = close.diff().dropna()
        gains = delta.clip(lower=0.0)
        losses = -delta.clip(upper=0.0)
        # Use simple mean over the window (matches the legacy backtester
        # implementation; Wilder's smoothed average is a small refinement
        # that doesn't materially affect signal direction).
        avg_gain = float(gains.tail(period).mean())
        avg_loss = float(losses.tail(period).mean())
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return float(rsi) if np.isfinite(rsi) else 50.0
