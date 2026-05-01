"""Base class for the new pandas-DataFrame strategy stack.

Strategy lifecycle
------------------

Each strategy carries a ``stage`` field that gates whether it is allowed to
emit live trades:

* ``paper``   - paper trading only (always enabled);
* ``shadow``  - live data, simulated orders (always enabled);
* ``canary``  - small live capital. Requires at least
  ``min_trades_for_promotion`` historical trades AND ``sharpe > 1.0``;
* ``live``    - full capital. Requires ``sharpe > 1.5`` AND
  ``win_rate > 45%`` AND the same minimum trade count.

The *minimum trade count* matters: the original spec gated canary/live on
Sharpe alone, which means a fresh strategy (Sharpe defaults to 0) could
never be promoted - the gate would lock itself shut forever. We require
at least 30 historical trades before applying the Sharpe / win-rate gates.

Spec deviations
---------------

* ``StrategyBase`` keeps a *copy* of ``params`` (the spec retained the
  caller's reference, leaking mutations).
* ``update_metrics`` no longer divides by ``running_max`` for max drawdown
  - that formula yields NaN/Inf when the running peak is non-positive
  (e.g. the first trade is a loss). We use the absolute peak-trough
  magnitude in PnL units, which is always finite and monotone.
* ``_hold_signal`` and ``_calculate_quantity`` are lifted into the base so
  every concrete strategy doesn't reimplement the same boilerplate.
* Sharpe annualisation factor is configurable via ``params["periods_per_year"]``
  (default 252 for daily bars). Intraday strategies should override.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


_VALID_STAGES: tuple[str, ...] = ("paper", "shadow", "canary", "live")
_KNOWN_REGIMES: frozenset[str] = frozenset({"trending_up", "trending_down", "ranging", "volatile"})

# Promote out of paper/shadow only after this many trades, otherwise the
# Sharpe / win-rate gates would block all fresh strategies forever.
DEFAULT_MIN_TRADES_FOR_PROMOTION: int = 30


@dataclass
class StrategySignal:
    """Structured signal produced by :meth:`StrategyBase.generate_signal`."""

    action: str  # "buy" | "sell" | "hold"
    confidence: float  # 0..1
    price_target: float | None
    stop_loss: float | None
    quantity: int
    reasoning: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "confidence": float(self.confidence),
            "price_target": None if self.price_target is None else float(self.price_target),
            "stop_loss": None if self.stop_loss is None else float(self.stop_loss),
            "quantity": int(self.quantity),
            "reasoning": self.reasoning,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class StrategyMetrics:
    """Performance metrics maintained by :meth:`StrategyBase.update_metrics`."""

    total_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0  # Peak-to-trough cumulative PnL, always >= 0.
    avg_win: float = 0.0
    avg_loss: float = 0.0
    expectancy: float = 0.0
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_trades": int(self.total_trades),
            "win_rate": float(self.win_rate),
            "profit_factor": float(self.profit_factor) if np.isfinite(self.profit_factor) else None,
            "sharpe_ratio": float(self.sharpe_ratio),
            "max_drawdown": float(self.max_drawdown),
            "avg_win": float(self.avg_win),
            "avg_loss": float(self.avg_loss),
            "expectancy": float(self.expectancy),
            "last_updated": self.last_updated.isoformat(),
        }


class StrategyBase(ABC):
    """Abstract base for pandas-DataFrame strategies."""

    #: Default percentage of capital to allocate per trade.
    default_position_pct: float = 0.10

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        # Copy the dict so caller mutations don't leak in.
        self.params: dict[str, Any] = dict(params or {})
        self.name: str = self.__class__.__name__
        stage = str(self.params.get("stage", "paper")).strip().lower()
        if stage not in _VALID_STAGES:
            logger.warning("strategy %s: unknown stage %r, falling back to paper", self.name, stage)
            stage = "paper"
        self.stage: str = stage
        self.metrics: StrategyMetrics = StrategyMetrics()
        self._trades: list[dict[str, Any]] = []
        # Minimum trades before applying canary/live gates.
        self.min_trades_for_promotion: int = int(
            self.params.get("min_trades_for_promotion", DEFAULT_MIN_TRADES_FOR_PROMOTION)
        )
        # Sharpe annualisation factor (252 trading days for daily, 252*6.5*60
        # ~= 98K for 1-minute bars - intraday strategies should override).
        self.periods_per_year: int = int(self.params.get("periods_per_year", 252))

    # -- abstract API --------------------------------------------------

    @abstractmethod
    def generate_signal(self, data: pd.DataFrame) -> StrategySignal:
        """Produce one :class:`StrategySignal` for the latest bar in ``data``."""

    @abstractmethod
    def suitable_for_regime(self, regime: str) -> float:
        """Return suitability score in ``[0, 1]`` for ``regime``."""

    # -- helpers usable by subclasses ----------------------------------

    def _hold_signal(self, *, reasoning: str = "no signal", confidence: float = 0.5) -> StrategySignal:
        return StrategySignal(
            action="hold",
            confidence=float(confidence),
            price_target=None,
            stop_loss=None,
            quantity=0,
            reasoning=reasoning,
        )

    def _calculate_quantity(self, price: float, *, allocation_pct: float | None = None) -> int:
        if not np.isfinite(price) or price <= 0:
            return 0
        capital = float(self.params.get("capital", 100000) or 0.0)
        pct = float(allocation_pct if allocation_pct is not None else self.default_position_pct)
        pct = max(0.0, min(1.0, pct))
        qty = int(capital * pct / price)
        return max(0, qty)

    @staticmethod
    def _has_columns(data: pd.DataFrame, columns: tuple[str, ...]) -> bool:
        return all(col in data.columns for col in columns)

    # -- metrics + lifecycle -------------------------------------------

    def update_metrics(self, trade_result: dict[str, Any]) -> None:
        """Append a trade and recompute summary metrics."""
        self._trades.append(dict(trade_result))
        n = len(self._trades)
        self.metrics.total_trades = n

        wins = [t for t in self._trades if float(t.get("pnl", 0.0)) > 0]
        losses = [t for t in self._trades if float(t.get("pnl", 0.0)) < 0]

        self.metrics.win_rate = len(wins) / n if n else 0.0
        total_wins = sum(float(t["pnl"]) for t in wins)
        total_losses = abs(sum(float(t["pnl"]) for t in losses))
        self.metrics.profit_factor = (
            total_wins / total_losses if total_losses > 0 else float("inf") if total_wins > 0 else 0.0
        )
        self.metrics.avg_win = total_wins / len(wins) if wins else 0.0
        self.metrics.avg_loss = total_losses / len(losses) if losses else 0.0
        self.metrics.expectancy = (
            self.metrics.win_rate * self.metrics.avg_win
            - (1.0 - self.metrics.win_rate) * self.metrics.avg_loss
        )

        # Sharpe over per-trade returns. Use ddof=1 (sample std).
        returns = np.asarray(
            [float(t.get("return_pct", 0.0)) for t in self._trades], dtype=float
        )
        if returns.size > 1 and np.std(returns, ddof=1) > 0:
            self.metrics.sharpe_ratio = float(
                np.mean(returns) / np.std(returns, ddof=1) * np.sqrt(self.periods_per_year)
            )
        else:
            self.metrics.sharpe_ratio = 0.0

        # Absolute peak-to-trough drawdown in PnL units.
        # The original spec divided by running_max which yields NaN/Inf when
        # the running peak is non-positive (very common for fresh strategies).
        cumulative = np.cumsum([float(t.get("pnl", 0.0)) for t in self._trades])
        running_max = np.maximum.accumulate(cumulative)
        drawdowns = running_max - cumulative
        self.metrics.max_drawdown = float(np.max(drawdowns)) if drawdowns.size else 0.0

        self.metrics.last_updated = datetime.now(timezone.utc)

    def can_trade(self) -> bool:
        """Return ``True`` when the current stage's gates pass."""
        if self.stage in ("paper", "shadow"):
            return True
        # canary / live gates require enough trades to be statistically meaningful.
        if self.metrics.total_trades < self.min_trades_for_promotion:
            return False
        if self.stage == "canary":
            return self.metrics.sharpe_ratio > 1.0
        if self.stage == "live":
            return self.metrics.sharpe_ratio > 1.5 and self.metrics.win_rate > 0.45
        return False

    # -- diagnostics ---------------------------------------------------

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"<{self.name} stage={self.stage} "
            f"trades={self.metrics.total_trades} sharpe={self.metrics.sharpe_ratio:.2f}>"
        )
