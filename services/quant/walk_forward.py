"""Walk-forward backtesting with purged, embargoed out-of-sample folds.

This module implements a *time-series-safe* variant of purged k-fold:

* Data is sorted by index (oldest first).
* Each fold's **test** slice is a contiguous chronological block.
* **Training** for that fold is strictly **before** ``test_start - embargo``,
  so there is no future leakage (the reference spec mistakenly included
  bars *after* the test window in the training mask).
* An **embargo** gap of ``embargo_pct * n`` bars sits between the last train
  bar and the first test bar to absorb serial correlation in labels
  (Lopez de Prado style).

The backtest loop consumes any object with ``generate_signal(df)`` returning
``StrategySignal`` (``services.quant.strategies.base``). Optional ``fit``
hook is called when present.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardConfig:
    """Walk-forward + cost + acceptance thresholds."""

    n_splits: int = 5
    train_size: float = 0.60
    test_size: float = 0.20
    embargo_pct: float = 0.01

    commission_bps: float = 5.0
    slippage_bps: float = 2.0

    min_sharpe: float = 1.0
    min_win_rate: float = 0.45
    max_drawdown: float = 0.15

    initial_capital: float = 100_000.0
    periods_per_year: float = 252.0


@dataclass
class FoldResult:
    fold_number: int
    train_start: datetime | pd.Timestamp | int | float | None
    train_end: datetime | pd.Timestamp | int | float | None
    test_start: datetime | pd.Timestamp | int | float | None
    test_end: datetime | pd.Timestamp | int | float | None
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    win_rate: float
    profit_factor: float
    max_drawdown: float
    total_trades: int
    total_return: float
    annualized_return: float
    trades: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class WalkForwardResult:
    strategy_name: str
    config: WalkForwardConfig
    fold_results: list[FoldResult]
    avg_sharpe: float
    avg_sortino: float
    avg_win_rate: float
    avg_profit_factor: float
    worst_drawdown: float
    passed: bool
    failure_reason: str | None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class PurgedKFold:
    """Time-ordered purged splits: train only before test (plus embargo gap)."""

    def __init__(self, n_splits: int = 5, embargo_pct: float = 0.01) -> None:
        self.n_splits = max(1, int(n_splits))
        self.embargo_pct = float(embargo_pct)

    def split(self, data: pd.DataFrame) -> list[tuple[pd.Index, pd.Index]]:
        if data is None or data.empty:
            raise ValueError("PurgedKFold.split requires non-empty data")

        ordered = data.sort_index()
        idx = ordered.index
        n = len(ordered)
        if n < 2:
            raise ValueError("PurgedKFold.split needs at least 2 rows")

        embargo = max(0, int(round(n * self.embargo_pct)))
        chunk = max(1, n // self.n_splits)
        splits: list[tuple[pd.Index, pd.Index]] = []

        for i in range(self.n_splits):
            t0 = i * chunk
            t1 = n if i == self.n_splits - 1 else min((i + 1) * chunk, n)
            if t0 >= t1:
                continue
            test_idx = idx[t0:t1]
            train_end_pos = max(0, t0 - embargo)
            train_idx = idx[:train_end_pos]
            splits.append((train_idx, test_idx))

        if not splits:
            raise ValueError("no splits generated")
        return splits


class WalkForwardBacktester:
    """Orchestrate purged walk-forward folds with costs and metric reporting."""

    def __init__(self, config: WalkForwardConfig | None = None) -> None:
        self.config = config or WalkForwardConfig()
        self.purged_kfold = PurgedKFold(
            n_splits=self.config.n_splits,
            embargo_pct=self.config.embargo_pct,
        )

    def run(self, strategy: Any, data: pd.DataFrame, symbol: str) -> WalkForwardResult:
        if not hasattr(strategy, "generate_signal"):
            raise TypeError("strategy must implement generate_signal(df)")

        ordered = data.sort_index()
        strat_name = getattr(strategy, "name", strategy.__class__.__name__)

        logger.info(
            "walk_forward: strategy=%s symbol=%s bars=%d splits=%d",
            strat_name,
            symbol,
            len(ordered),
            self.config.n_splits,
        )

        splits = self.purged_kfold.split(ordered)
        fold_results: list[FoldResult] = []

        for i, (train_idx, test_idx) in enumerate(splits):
            train_data = ordered.loc[train_idx]
            test_data = ordered.loc[test_idx]

            if hasattr(strategy, "fit"):
                try:
                    strategy.fit(train_data)
                except Exception as exc:
                    logger.warning("walk_forward: strategy.fit failed: %s", exc)

            fold_res = self._backtest_fold(
                strategy,
                test_data,
                fold_num=i + 1,
                train_data=train_data,
            )
            fold_results.append(fold_res)
            logger.info(
                "walk_forward: fold %d/%d sharpe=%.3f win_rate=%.1f%% trades=%d",
                i + 1,
                len(splits),
                fold_res.sharpe_ratio,
                fold_res.win_rate * 100,
                fold_res.total_trades,
            )

        avg_sharpe = float(np.mean([f.sharpe_ratio for f in fold_results]))
        avg_sortino = float(np.mean([f.sortino_ratio for f in fold_results]))
        avg_win_rate = float(np.mean([f.win_rate for f in fold_results]))
        pfs = [_finite_profit_factor(f.profit_factor) for f in fold_results]
        avg_pf = float(np.mean(pfs)) if pfs else 0.0
        worst_dd = float(max((f.max_drawdown for f in fold_results), default=0.0))

        passed, reason = self._validate_results(avg_sharpe, avg_win_rate, worst_dd)

        result = WalkForwardResult(
            strategy_name=strat_name,
            config=self.config,
            fold_results=fold_results,
            avg_sharpe=avg_sharpe,
            avg_sortino=avg_sortino,
            avg_win_rate=avg_win_rate,
            avg_profit_factor=avg_pf,
            worst_drawdown=worst_dd,
            passed=passed,
            failure_reason=reason,
        )
        logger.info(
            "walk_forward: done avg_sharpe=%.3f passed=%s",
            avg_sharpe,
            passed,
        )
        return result

    def _backtest_fold(
        self,
        strategy: Any,
        data: pd.DataFrame,
        fold_num: int,
        train_data: pd.DataFrame,
    ) -> FoldResult:
        required = {"open", "high", "low", "close"}
        if not required <= set(data.columns):
            raise ValueError(f"OHLCV frame must contain columns {required}")

        capital = float(self.config.initial_capital)
        equity_curve: list[float] = [capital]
        trades: list[dict[str, Any]] = []
        position: dict[str, Any] | None = None

        slippage = self.config.slippage_bps / 10_000.0
        comm = self.config.commission_bps / 10_000.0

        for i in range(len(data)):
            bar = data.iloc[i]
            current_data = data.iloc[: i + 1]

            if position is None:
                sig = strategy.generate_signal(current_data)
                action = (sig.action or "hold").lower()
                qty = int(sig.quantity or 0)
                if action == "buy" and qty > 0:
                    entry_raw = float(bar["close"])
                    entry_price = entry_raw * (1.0 + slippage)
                    notional = entry_price * qty
                    entry_comm = notional * comm
                    position = {
                        "entry_time": data.index[i],
                        "entry_bar": i,
                        "entry_price": entry_price,
                        "quantity": qty,
                        "commission_paid": entry_comm,
                        "target": sig.price_target,
                        "stop": sig.stop_loss,
                    }
                    capital -= entry_comm
            else:
                high = float(bar["high"])
                low = float(bar["low"])
                close = float(bar["close"])
                exit_price: float | None = None

                st = position.get("stop")
                tg = position.get("target")
                if st is not None and low <= float(st):
                    exit_price = float(st)
                elif tg is not None and high >= float(tg):
                    exit_price = float(tg)
                else:
                    sig = strategy.generate_signal(current_data)
                    if (sig.action or "hold").lower() == "sell":
                        exit_price = close * (1.0 - slippage)

                if exit_price is not None:
                    qty = int(position["quantity"])
                    exit_comm = exit_price * qty * comm
                    gross = (exit_price - float(position["entry_price"])) * qty
                    pnl = gross - float(position["commission_paid"]) - exit_comm
                    capital += gross - exit_comm

                    denom = float(position["entry_price"]) * qty
                    ret_pct = (pnl / denom) * 100.0 if denom else 0.0

                    trades.append(
                        {
                            "entry_time": position["entry_time"],
                            "exit_time": data.index[i],
                            "entry_price": position["entry_price"],
                            "exit_price": exit_price,
                            "quantity": qty,
                            "pnl": pnl,
                            "return_pct": ret_pct,
                            "duration_bars": i - int(position["entry_bar"]),
                        }
                    )
                    position = None

            equity_curve.append(capital)

        metrics = self._calculate_metrics(trades, equity_curve, data)

        tr_start = train_data.index[0] if len(train_data) else None
        tr_end = train_data.index[-1] if len(train_data) else None
        te_start = data.index[0] if len(data) else None
        te_end = data.index[-1] if len(data) else None

        return FoldResult(
            fold_number=fold_num,
            train_start=tr_start,
            train_end=tr_end,
            test_start=te_start,
            test_end=te_end,
            sharpe_ratio=float(metrics["sharpe"]),
            sortino_ratio=float(metrics["sortino"]),
            calmar_ratio=float(metrics["calmar"]),
            win_rate=float(metrics["win_rate"]),
            profit_factor=float(metrics["profit_factor"]),
            max_drawdown=float(metrics["max_drawdown"]),
            total_trades=len(trades),
            total_return=float(metrics["total_return"]),
            annualized_return=float(metrics["annualized_return"]),
            trades=trades,
        )

    def _calculate_metrics(
        self,
        trades: list[dict[str, Any]],
        equity_curve: list[float],
        data: pd.DataFrame,
    ) -> dict[str, float]:
        if not trades:
            return {
                "sharpe": 0.0,
                "sortino": 0.0,
                "calmar": 0.0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "max_drawdown": 0.0,
                "total_return": 0.0,
                "annualized_return": 0.0,
            }

        returns = np.array([t["return_pct"] / 100.0 for t in trades], dtype=float)
        wins = returns[returns > 0]
        losses = returns[returns < 0]
        win_rate = float(len(wins) / len(trades))

        total_wins = float(wins.sum()) if wins.size else 0.0
        total_losses = float(abs(losses.sum())) if losses.size else 0.0
        profit_factor = (
            total_wins / total_losses
            if total_losses > 0
            else (float("inf") if total_wins > 0 else 0.0)
        )

        std_ret = float(np.std(returns, ddof=1)) if returns.size > 1 else 0.0
        if std_ret > 0:
            sharpe = float(np.mean(returns) / std_ret * math.sqrt(self.config.periods_per_year))
        else:
            sharpe = 0.0

        downside = returns[returns < 0]
        dstd = float(np.std(downside, ddof=1)) if downside.size > 1 else 0.0
        if dstd > 0:
            sortino = float(np.mean(returns) / dstd * math.sqrt(self.config.periods_per_year))
        elif std_ret > 0:
            sortino = sharpe
        else:
            sortino = 0.0

        eq = np.array(equity_curve, dtype=float)
        peak = np.maximum.accumulate(eq)
        peak_safe = np.where(peak > 0, peak, 1.0)
        dd = (peak - eq) / peak_safe
        max_dd = float(np.max(dd)) if dd.size else 0.0

        total_return = float(eq[-1] / eq[0] - 1.0) if eq[0] > 0 else 0.0
        ann = _annualized_return(data.index, total_return)
        calmar = ann / max_dd if max_dd > 1e-12 else 0.0

        return {
            "sharpe": sharpe,
            "sortino": sortino,
            "calmar": calmar,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "max_drawdown": max_dd,
            "total_return": total_return,
            "annualized_return": ann,
        }

    def _validate_results(
        self,
        avg_sharpe: float,
        avg_win_rate: float,
        worst_dd: float,
    ) -> tuple[bool, str | None]:
        if avg_sharpe < self.config.min_sharpe:
            return False, f"Sharpe {avg_sharpe:.2f} < {self.config.min_sharpe}"
        if avg_win_rate < self.config.min_win_rate:
            return False, f"Win rate {avg_win_rate:.1%} < {self.config.min_win_rate:.1%}"
        if worst_dd > self.config.max_drawdown:
            return False, f"Max DD {worst_dd:.1%} > {self.config.max_drawdown:.1%}"
        return True, None


def _annualized_return(index: pd.Index, total_return: float) -> float:
    if len(index) < 2:
        return 0.0
    try:
        delta = index[-1] - index[0]
        if hasattr(delta, "days"):
            days = max(1, int(delta.days))
        elif hasattr(delta, "total_seconds"):
            days = max(1, int(delta.total_seconds() / 86400.0))
        else:
            days = max(1, len(index) - 1)
    except Exception:
        days = max(1, len(index) - 1)
    return float((1.0 + total_return) ** (365.0 / days) - 1.0)


def _finite_profit_factor(pf: float, cap: float = 50.0) -> float:
    if not math.isfinite(pf):
        return cap
    return float(min(pf, cap))


__all__ = [
    "FoldResult",
    "PurgedKFold",
    "WalkForwardBacktester",
    "WalkForwardConfig",
    "WalkForwardResult",
]
