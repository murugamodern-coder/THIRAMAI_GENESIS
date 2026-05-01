"""Multi-strategy trading engine.

This is a separate strategy stack from the legacy
:mod:`services.quant.backtester` API (which uses lists of candle dicts and
is still wired into ``run_backtest`` / :class:`StrategyRegistry`). The new
classes here use pandas DataFrames and produce structured
:class:`StrategySignal` objects so they can be selected dynamically per
market regime, tracked per-strategy, and lifecycle-gated through
paper -> shadow -> canary -> live.

Old ``services.quant.backtester.RSIMACDStrategy`` is intentionally left
untouched - the new pandas-based RSI/MACD lives at
:class:`services.quant.strategies.rsi_macd.RSIMACDStrategy`. They coexist."""

from services.quant.strategies.base import (
    StrategyBase,
    StrategyMetrics,
    StrategySignal,
)
from services.quant.strategies.breakout import BreakoutStrategy
from services.quant.strategies.gap import GapStrategy
from services.quant.strategies.mean_reversion import VWAPMeanReversionStrategy
from services.quant.strategies.momentum import MomentumStrategy
from services.quant.strategies.pairs import PairsStrategy
from services.quant.strategies.rsi_macd import RSIMACDStrategy

__all__ = [
    "BreakoutStrategy",
    "GapStrategy",
    "MomentumStrategy",
    "PairsStrategy",
    "RSIMACDStrategy",
    "StrategyBase",
    "StrategyMetrics",
    "StrategySignal",
    "VWAPMeanReversionStrategy",
]
