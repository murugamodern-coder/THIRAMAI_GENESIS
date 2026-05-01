"""Pick the best strategy for the current regime.

Score formula::

    score = suitability_weight * suitable_for_regime(regime)
          + performance_weight * clamp(sharpe / sharpe_cap, 0, 1)

Spec deviations
---------------

* The original ``StrategySelector`` allowed negative Sharpe to pull the
  combined score below zero - a fresh strategy with a high suitability
  score could lose to one with no track record. We clamp the performance
  term into ``[0, 1]`` before weighting.
* Strategies whose ``can_trade()`` is False (e.g. canary stage but still
  too few trades) can be optionally excluded via
  ``require_can_trade=True``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from typing import Any

import pandas as pd

from services.quant.regime_detector import RegimeDetector
from services.quant.strategies.base import StrategyBase

logger = logging.getLogger(__name__)


class StrategySelector:
    """Regime-aware strategy picker."""

    def __init__(
        self,
        strategies: Iterable[StrategyBase],
        *,
        regime_detector: RegimeDetector | None = None,
        suitability_weight: float = 0.7,
        performance_weight: float = 0.3,
        sharpe_cap: float = 2.0,
        min_trades_for_performance: int = 10,
    ) -> None:
        self.strategies: list[StrategyBase] = list(strategies)
        if not self.strategies:
            raise ValueError("StrategySelector needs at least one strategy")
        self.regime_detector = regime_detector or RegimeDetector()
        if not 0.0 <= suitability_weight <= 1.0:
            raise ValueError("suitability_weight must be in [0, 1]")
        if not 0.0 <= performance_weight <= 1.0:
            raise ValueError("performance_weight must be in [0, 1]")
        self.suitability_weight = float(suitability_weight)
        self.performance_weight = float(performance_weight)
        self.sharpe_cap = max(0.1, float(sharpe_cap))
        self.min_trades_for_performance = max(0, int(min_trades_for_performance))
        self.current_strategy: StrategyBase | None = None
        self.current_regime: str | None = None

    # -- public --------------------------------------------------------

    def select(
        self,
        prices: pd.Series,
        *,
        require_can_trade: bool = False,
    ) -> StrategyBase:
        regime_payload = self.regime_detector.detect(prices)
        regime = str(regime_payload.get("regime", "unknown"))
        self.current_regime = regime
        scored = self.score_all(regime, require_can_trade=require_can_trade)
        if not scored:
            # Nothing passed the filter - fall back to highest-suitability
            # candidate ignoring the can_trade gate.
            scored = self.score_all(regime, require_can_trade=False)
        best, best_score = max(scored, key=lambda pair: pair[1])
        logger.info(
            "strategy_selector: regime=%s pick=%s score=%.3f",
            regime, best.name, best_score,
        )
        self.current_strategy = best
        return best

    def score_all(
        self,
        regime: str,
        *,
        require_can_trade: bool = False,
    ) -> list[tuple[StrategyBase, float]]:
        out: list[tuple[StrategyBase, float]] = []
        for strategy in self.strategies:
            if require_can_trade and not strategy.can_trade():
                continue
            out.append((strategy, self._score(strategy, regime)))
        return out

    def explain(self, regime: str) -> list[dict[str, Any]]:
        """Return the per-strategy score breakdown for ``regime``."""
        explanations: list[dict[str, Any]] = []
        for strategy in self.strategies:
            suitability = float(strategy.suitable_for_regime(regime))
            performance = self._performance_term(strategy)
            score = self._score(strategy, regime)
            explanations.append({
                "name": strategy.name,
                "stage": strategy.stage,
                "suitability": suitability,
                "performance": performance,
                "score": score,
                "can_trade": strategy.can_trade(),
                "trades": strategy.metrics.total_trades,
                "sharpe": strategy.metrics.sharpe_ratio,
            })
        explanations.sort(key=lambda d: d["score"], reverse=True)
        return explanations

    # -- internals -----------------------------------------------------

    def _score(self, strategy: StrategyBase, regime: str) -> float:
        suitability = float(strategy.suitable_for_regime(regime))
        performance = self._performance_term(strategy)
        return self.suitability_weight * suitability + self.performance_weight * performance

    def _performance_term(self, strategy: StrategyBase) -> float:
        if strategy.metrics.total_trades < self.min_trades_for_performance:
            return 0.0
        sharpe = float(strategy.metrics.sharpe_ratio)
        return max(0.0, min(1.0, sharpe / self.sharpe_cap))


__all__ = ["StrategySelector"]
