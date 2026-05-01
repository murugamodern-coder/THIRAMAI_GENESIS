"""Breakout strategy.

Entry rule
----------

Buy when the latest close exceeds the highest *prior* high over the
``lookback`` window (default 20 bars) by ``buffer_pct`` (default 0.1%).
The prior-high window deliberately *excludes* the current bar, so the
breakout can fire on the bar that actually breaches resistance - the
spec's window included today, which makes the strict ``>`` condition
unsatisfiable when today is the new high.
"""

from __future__ import annotations

import pandas as pd

from services.quant.strategies.base import StrategyBase, StrategySignal


class BreakoutStrategy(StrategyBase):
    """Donchian-style breakout. Best for trending markets."""

    default_position_pct = 0.10

    def generate_signal(self, data: pd.DataFrame) -> StrategySignal:
        lookback = int(self.params.get("lookback", 20))
        buffer_pct = float(self.params.get("buffer_pct", 0.001))
        profit_pct = float(self.params.get("profit_pct", 0.025))
        stop_pct = float(self.params.get("stop_pct", 0.015))

        if len(data) < lookback + 1 or not self._has_columns(data, ("high", "close")):
            return self._hold_signal(reasoning="insufficient data")

        # Look at the lookback window *before* the current bar so a fresh
        # breakout can actually fire on the bar that breaches the level.
        prior = data["high"].iloc[-lookback - 1 : -1]
        prior_high = float(prior.max())
        current_price = float(data["close"].iloc[-1])

        if not (prior_high > 0 and current_price > 0):
            return self._hold_signal(reasoning="invalid prices")

        if current_price > prior_high * (1.0 + buffer_pct):
            return StrategySignal(
                action="buy",
                confidence=0.75,
                price_target=current_price * (1.0 + profit_pct),
                stop_loss=current_price * (1.0 - stop_pct),
                quantity=self._calculate_quantity(current_price),
                reasoning=f"Breakout above {lookback}-bar high ({prior_high:.2f})",
            )

        return self._hold_signal(reasoning="no breakout")

    def suitable_for_regime(self, regime: str) -> float:
        return {
            "trending_up": 0.9,
            "trending_down": 0.3,
            "ranging": 0.2,
            "volatile": 0.4,
        }.get(regime, 0.5)
