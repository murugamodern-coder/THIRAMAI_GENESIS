"""Opening-gap fade strategy.

Plays the well-documented mean-reverting tendency of opening gaps: when
the latest open prints far above (or below) the prior close, the close
often re-traces some portion of the gap during the session. This is a
*fade* implementation - we sell into a gap-up and buy into a gap-down.
The threshold defaults to 1.5%; small gaps don't fade reliably.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from services.quant.strategies.base import StrategyBase, StrategySignal


class GapStrategy(StrategyBase):
    """Best for ranging markets and mean-reverting opens."""

    default_position_pct = 0.08

    def generate_signal(self, data: pd.DataFrame) -> StrategySignal:
        gap_threshold = float(self.params.get("gap_threshold_pct", 0.015))
        target_fraction = float(self.params.get("target_fraction", 0.5))  # close half the gap
        stop_pct = float(self.params.get("stop_pct", 0.01))

        if len(data) < 2 or not self._has_columns(data, ("open", "close")):
            return self._hold_signal(reasoning="insufficient data")

        prior_close = float(data["close"].iloc[-2])
        today_open = float(data["open"].iloc[-1])
        today_close = float(data["close"].iloc[-1])
        if prior_close <= 0 or today_open <= 0:
            return self._hold_signal(reasoning="invalid prices")

        gap_pct = (today_open / prior_close) - 1.0
        if not np.isfinite(gap_pct):
            return self._hold_signal(reasoning="non-finite gap")

        # Distance from open we expect price to retrace.
        target_move = abs(gap_pct) * target_fraction

        if gap_pct >= gap_threshold:
            # Gap-up: fade by selling, target a partial fill of the gap.
            return StrategySignal(
                action="sell",
                confidence=0.65,
                price_target=today_close * (1.0 - target_move),
                stop_loss=today_close * (1.0 + stop_pct),
                quantity=self._calculate_quantity(today_close),
                reasoning=f"gap up {gap_pct:.2%}, fading",
            )
        if gap_pct <= -gap_threshold:
            return StrategySignal(
                action="buy",
                confidence=0.65,
                price_target=today_close * (1.0 + target_move),
                stop_loss=today_close * (1.0 - stop_pct),
                quantity=self._calculate_quantity(today_close),
                reasoning=f"gap down {gap_pct:.2%}, fading",
            )
        return self._hold_signal(reasoning=f"gap too small ({gap_pct:.2%})")

    def suitable_for_regime(self, regime: str) -> float:
        return {
            "trending_up": 0.3,
            "trending_down": 0.3,
            "ranging": 0.85,
            "volatile": 0.55,
        }.get(regime, 0.5)
