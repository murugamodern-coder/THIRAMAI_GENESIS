"""Statistical-arbitrage pairs strategy.

A pairs trade exploits the assumption that two cointegrated instruments
have a stable spread. When the spread is far above its rolling mean we
short the pair (sell the leader, buy the laggard); far below, we go long.
A full implementation would also test for cointegration (Engle-Granger,
Johansen) and recompute the hedge ratio; this minimal version takes a
fixed hedge ratio from ``params["hedge_ratio"]`` (default 1.0) and
operates on the rolling Z-score of the spread.

DataFrame contract
------------------

The DataFrame must have a ``close`` column for the primary instrument and
the secondary series must be supplied either:

* as ``params["secondary_series"]`` - a ``pandas.Series`` aligned to the
  same index, or
* as a column called ``close_b`` in ``data``.

If neither is supplied the strategy emits a hold signal with a clear
reasoning - we don't pretend to trade a pair we don't have data for.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from services.quant.strategies.base import StrategyBase, StrategySignal


class PairsStrategy(StrategyBase):
    """Best for ranging markets - assumes spread mean-reverts."""

    default_position_pct = 0.06

    def generate_signal(self, data: pd.DataFrame) -> StrategySignal:
        window = int(self.params.get("window", 30))
        z_entry = float(self.params.get("z_entry", 2.0))
        hedge_ratio = float(self.params.get("hedge_ratio", 1.0))
        stop_pct = float(self.params.get("stop_pct", 0.015))

        if len(data) < window + 1 or "close" not in data.columns:
            return self._hold_signal(reasoning="insufficient data")

        secondary = self._get_secondary(data)
        if secondary is None:
            return self._hold_signal(reasoning="no secondary series for pair")
        if len(secondary) != len(data):
            return self._hold_signal(reasoning="secondary series length mismatch")

        primary = data["close"].astype(float).reset_index(drop=True)
        secondary_aligned = pd.Series(secondary, dtype=float).reset_index(drop=True)
        spread = primary - hedge_ratio * secondary_aligned

        recent = spread.tail(window)
        mean = float(recent.mean())
        std = float(recent.std(ddof=1))
        if not np.isfinite(std) or std <= 0:
            return self._hold_signal(reasoning="spread variance collapsed")

        current_spread = float(spread.iloc[-1])
        z = (current_spread - mean) / std
        current_price = float(primary.iloc[-1])
        if current_price <= 0:
            return self._hold_signal(reasoning="invalid price")

        if z >= z_entry:
            return StrategySignal(
                action="sell",
                confidence=0.7,
                price_target=current_price - (current_spread - mean),
                stop_loss=current_price * (1.0 + stop_pct),
                quantity=self._calculate_quantity(current_price),
                reasoning=f"pair z-score {z:.2f} >= {z_entry}, fading rich",
            )
        if z <= -z_entry:
            return StrategySignal(
                action="buy",
                confidence=0.7,
                price_target=current_price + (mean - current_spread),
                stop_loss=current_price * (1.0 - stop_pct),
                quantity=self._calculate_quantity(current_price),
                reasoning=f"pair z-score {z:.2f} <= -{z_entry}, fading cheap",
            )
        return self._hold_signal(reasoning=f"pair z-score {z:.2f} within band")

    def suitable_for_regime(self, regime: str) -> float:
        return {
            "trending_up": 0.4,
            "trending_down": 0.4,
            "ranging": 0.85,
            "volatile": 0.5,
        }.get(regime, 0.5)

    def _get_secondary(self, data: pd.DataFrame) -> pd.Series | None:
        secondary = self.params.get("secondary_series")
        if secondary is not None:
            try:
                return pd.Series(secondary, dtype=float)
            except (TypeError, ValueError):
                return None
        if "close_b" in data.columns:
            return data["close_b"].astype(float)
        return None
