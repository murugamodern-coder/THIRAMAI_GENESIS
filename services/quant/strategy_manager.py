"""Lifecycle management for the new pandas-DataFrame strategy stack.

This is intentionally separate from the legacy
:class:`services.quant.strategy_registry.StrategyRegistry` (class-method
based, candle-list strategies) - both registries coexist so the legacy
``run_backtest()`` flow keeps working unchanged.

A single :class:`StrategyManager` instance owns a set of named
:class:`StrategyBase` strategies and exposes them by name, by stage, or
filtered by ``can_trade()``. Default registration includes all six built-in
strategies in the ``paper`` stage.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from services.quant.strategies import (
    BreakoutStrategy,
    GapStrategy,
    MomentumStrategy,
    PairsStrategy,
    RSIMACDStrategy,
    StrategyBase,
    VWAPMeanReversionStrategy,
)

logger = logging.getLogger(__name__)


_DEFAULT_REGISTRY: tuple[tuple[str, type[StrategyBase]], ...] = (
    ("breakout", BreakoutStrategy),
    ("mean_reversion", VWAPMeanReversionStrategy),
    ("momentum", MomentumStrategy),
    ("gap", GapStrategy),
    ("pairs", PairsStrategy),
    ("rsi_macd", RSIMACDStrategy),
)


class StrategyManager:
    """Per-instance registry of pandas-DataFrame strategies."""

    def __init__(
        self,
        *,
        register_defaults: bool = True,
        default_params: dict[str, Any] | None = None,
    ) -> None:
        self.strategies: dict[str, StrategyBase] = {}
        self._lock = threading.Lock()
        if register_defaults:
            base_params = dict(default_params or {"capital": 100000, "stage": "paper"})
            for name, cls in _DEFAULT_REGISTRY:
                self.register(name, cls(base_params))

    # -- registry ------------------------------------------------------

    def register(self, name: str, strategy: StrategyBase) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("strategy name must be a non-empty string")
        if not isinstance(strategy, StrategyBase):
            raise TypeError(f"strategy must be a StrategyBase, got {type(strategy).__name__}")
        with self._lock:
            if name in self.strategies:
                logger.info("strategy_manager: replacing existing strategy %r", name)
            self.strategies[name] = strategy

    def unregister(self, name: str) -> bool:
        with self._lock:
            return self.strategies.pop(name, None) is not None

    # -- lookup --------------------------------------------------------

    def get(self, name: str) -> StrategyBase | None:
        return self.strategies.get(name)

    def get_or_raise(self, name: str) -> StrategyBase:
        strategy = self.strategies.get(name)
        if strategy is None:
            raise KeyError(f"strategy {name!r} not registered")
        return strategy

    def get_all(self) -> list[StrategyBase]:
        return list(self.strategies.values())

    def names(self) -> list[str]:
        return list(self.strategies.keys())

    def get_by_stage(self, stage: str) -> list[StrategyBase]:
        target = (stage or "").strip().lower()
        return [s for s in self.strategies.values() if s.stage == target]

    def tradable(self) -> list[StrategyBase]:
        return [s for s in self.strategies.values() if s.can_trade()]

    # -- introspection --------------------------------------------------

    def __len__(self) -> int:
        return len(self.strategies)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self.strategies


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------


_singleton: StrategyManager | None = None
_singleton_lock = threading.Lock()


def get_strategy_manager() -> StrategyManager:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = StrategyManager()
    return _singleton


def reset_strategy_manager() -> None:
    """Test-only helper that drops the singleton."""
    global _singleton
    with _singleton_lock:
        _singleton = None


__all__ = [
    "StrategyManager",
    "get_strategy_manager",
    "reset_strategy_manager",
]
