"""VWAP mean-reversion strategy.

Entry rule
----------

If the latest close is more than ``threshold_pct`` (default 2%) below the
session VWAP, go long; if it's more than ``threshold_pct`` above, go short.
The session VWAP is computed over **the entire DataFrame passed in**, so
callers should pass intraday bars from a single session - feeding multi-year
daily candles in here would average prices across regimes and produce a
meaningless reference. We document this rather than try to detect "session
boundaries" automatically.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from services.quant.strategies.base import StrategyBase, StrategySignal


class VWAPMeanReversionStrategy(StrategyBase):
    """Best for ranging / choppy markets."""

    default_position_pct = 0.10

    def generate_signal(self, data: pd.DataFrame) -> StrategySignal:
        min_bars = int(self.params.get("min_bars", 20))
        threshold_pct = float(self.params.get("threshold_pct", 0.02))
        stop_pct = float(self.params.get("stop_pct", 0.01))

        if len(data) < min_bars or not self._has_columns(data, ("close", "volume")):
            return self._hold_signal(reasoning="insufficient data")

        volume_total = float(data["volume"].sum())
        if volume_total <= 0:
            return self._hold_signal(reasoning="zero volume - VWAP undefined")

        vwap = float((data["close"] * data["volume"]).sum() / volume_total)
        current_price = float(data["close"].iloc[-1])
        if not (np.isfinite(vwap) and vwap > 0 and current_price > 0):
            return self._hold_signal(reasoning="invalid prices")

        distance_pct = (current_price - vwap) / vwap

        if distance_pct < -threshold_pct:
            return StrategySignal(
                action="buy",
                confidence=0.7,
                price_target=vwap,
                stop_loss=current_price * (1.0 - stop_pct),
                quantity=self._calculate_quantity(current_price),
                reasoning=f"price {abs(distance_pct):.1%} below VWAP ({vwap:.2f})",
            )
        if distance_pct > threshold_pct:
            return StrategySignal(
                action="sell",
                confidence=0.7,
                price_target=vwap,
                stop_loss=current_price * (1.0 + stop_pct),
                quantity=self._calculate_quantity(current_price),
                reasoning=f"price {distance_pct:.1%} above VWAP ({vwap:.2f})",
            )

        return self._hold_signal(reasoning="price near VWAP")

    def suitable_for_regime(self, regime: str) -> float:
        return {
            "trending_up": 0.3,
            "trending_down": 0.3,
            "ranging": 0.9,
            "volatile": 0.6,
        }.get(regime, 0.5)
