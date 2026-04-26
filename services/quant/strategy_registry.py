"""Registry of trading strategies (lookup by name or by market regime)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Type

from services.quant.backtester import RSIMACDStrategy, StrategyBase

logger = logging.getLogger(__name__)


@dataclass
class StrategyInfo:
    name: str
    description: str
    strategy_class: Type[StrategyBase]
    is_active: bool = True
    best_for: str = "trending"  # trending | ranging | volatile


class StrategyRegistry:
    """Process-wide registry of available trading strategies."""

    _strategies: dict[str, StrategyInfo] = {}

    @classmethod
    def register(cls, info: StrategyInfo) -> None:
        cls._strategies[info.name] = info
        logger.info("strategy_registered name=%s", info.name)

    @classmethod
    def get(cls, name: str) -> StrategyBase:
        info = cls._strategies.get(name)
        if not info:
            raise ValueError(f"Strategy {name} not found")
        return info.strategy_class()

    @classmethod
    def list_active(cls) -> list[StrategyInfo]:
        return [s for s in cls._strategies.values() if s.is_active]

    @classmethod
    def get_best_for_regime(cls, regime: str) -> StrategyBase:
        for info in cls._strategies.values():
            if info.is_active and info.best_for == regime:
                return info.strategy_class()
        return RSIMACDStrategy()


StrategyRegistry.register(
    StrategyInfo(
        name="rsi_macd",
        description="Classic RSI + MACD momentum strategy",
        strategy_class=RSIMACDStrategy,
        is_active=True,
        best_for="trending",
    )
)
