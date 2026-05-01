"""Tests for walk-forward purged CV and broker GTT stop automation."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from services.quant.broker_stops import BrokerStopManager
from services.quant.strategies.base import StrategySignal
from services.quant.walk_forward import (
    FoldResult,
    PurgedKFold,
    WalkForwardBacktester,
    WalkForwardConfig,
    WalkForwardResult,
    _annualized_return,
    _finite_profit_factor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ohlcv(n: int = 120, start: float = 100.0, drift: float = 0.001) -> pd.DataFrame:
    """Upward-drifting synthetic daily OHLCV (DatetimeIndex, oldest first)."""
    rng = np.random.default_rng(42)
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    closes = []
    p = start
    for _ in range(n):
        p *= 1.0 + drift + rng.normal(0, 0.004)
        closes.append(p)
    closes = np.array(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": closes * 0.998,
            "high": closes * 1.002,
            "low": closes * 0.996,
            "close": closes,
            "volume": rng.integers(1000, 5000, size=n),
        },
        index=idx,
    )


class _AlwaysBuyStrategy:
    name = "AlwaysBuy"

    def generate_signal(self, data: pd.DataFrame) -> StrategySignal:
        if len(data) < 2:
            return StrategySignal("hold", 0.5, None, None, 0, "wait")
        price = float(data["close"].iloc[-1])
        return StrategySignal(
            "buy",
            0.9,
            price * 1.50,
            price * 0.90,
            10,
            "always long",
        )

    def fit(self, _train: pd.DataFrame) -> None:
        return


class _BuyThenSellStrategy:
    """Buy on first bar with room, exit on explicit sell after ``sell_after`` bars."""

    name = "BuyThenSell"

    def __init__(self, sell_after: int = 8) -> None:
        self._sell_after = sell_after

    def generate_signal(self, data: pd.DataFrame) -> StrategySignal:
        n = len(data)
        price = float(data["close"].iloc[-1])
        if n == 3:
            return StrategySignal(
                "buy",
                1.0,
                price * 1.05,
                price * 0.99,
                5,
                "enter",
            )
        if n >= self._sell_after:
            return StrategySignal("sell", 1.0, None, None, 5, "exit")
        return StrategySignal("hold", 0.5, None, None, 0, "wait")


# ===========================================================================
# PurgedKFold
# ===========================================================================


def test_purged_kfold_rejects_empty():
    with pytest.raises(ValueError, match="non-empty"):
        PurgedKFold().split(pd.DataFrame())


def test_purged_kfold_rejects_single_row():
    df = _ohlcv(1)
    with pytest.raises(ValueError, match="at least 2"):
        PurgedKFold(n_splits=3).split(df)


def test_purged_kfold_produces_requested_folds():
    df = _ohlcv(100)
    pk = PurgedKFold(n_splits=5, embargo_pct=0.02)
    splits = pk.split(df)
    assert len(splits) >= 1
    assert all(len(te) > 0 for _, te in splits)


def test_purged_kfold_train_is_strictly_before_test_with_embargo():
    df = _ohlcv(60)
    embargo_pct = 0.05
    pk = PurgedKFold(n_splits=4, embargo_pct=embargo_pct)
    ordered = df.sort_index()
    n = len(ordered)
    embargo = int(round(n * embargo_pct))
    for train_idx, test_idx in pk.split(ordered):
        if len(train_idx) == 0:
            continue
        assert train_idx.max() < test_idx.min()
        gap = ordered.index.get_loc(test_idx[0]) - ordered.index.get_loc(train_idx[-1]) - 1
        assert gap >= embargo - 1  # at least ~embargo bars between last train and test start


def test_purged_kfold_embargo_zero_allows_adjacent_train_test():
    df = _ohlcv(40)
    pk = PurgedKFold(n_splits=4, embargo_pct=0.0)
    splits = pk.split(df)
    tr, te = splits[1]
    if len(tr) > 0:
        assert tr[-1] <= te[0] or df.index.get_loc(tr[-1]) == df.index.get_loc(te[0]) - 1


def test_purged_kfold_sorted_input_not_required():
    df = _ohlcv(50).sort_index(ascending=False)  # newest first
    splits = PurgedKFold(n_splits=5).split(df)
    assert len(splits) >= 1


# ===========================================================================
# WalkForwardBacktester — integration
# ===========================================================================


def test_walk_forward_run_with_multi_strategy_engine_class():
    from services.quant.strategies.breakout import BreakoutStrategy

    df = _ohlcv(80, drift=0.02)
    cfg = WalkForwardConfig(n_splits=4, min_sharpe=-10.0, min_win_rate=0.0, max_drawdown=1.0)
    wf = WalkForwardBacktester(cfg)
    res = wf.run(BreakoutStrategy({"capital": 100_000, "lookback": 5}), df, "RELIANCE")
    assert isinstance(res, WalkForwardResult)
    assert res.strategy_name == "BreakoutStrategy"
    assert len(res.fold_results) >= 1
    assert res.config.n_splits == 4


def test_walk_forward_requires_generate_signal():
    wf = WalkForwardBacktester(WalkForwardConfig(n_splits=2))
    with pytest.raises(TypeError, match="generate_signal"):
        wf.run(object(), _ohlcv(30), "X")


def test_walk_forward_calls_fit_when_present():
    strat = MagicMock(wraps=_AlwaysBuyStrategy())
    strat.generate_signal = _AlwaysBuyStrategy.generate_signal.__get__(strat, MagicMock)
    wf = WalkForwardBacktester(WalkForwardConfig(n_splits=3, min_sharpe=-99, min_win_rate=0, max_drawdown=1.0))
    wf.run(strat, _ohlcv(50), "X")
    assert strat.fit.called


def test_walk_forward_fit_exception_is_swallowed():
    class _BadFit(_AlwaysBuyStrategy):
        def fit(self, _):
            raise RuntimeError("no")

    wf = WalkForwardBacktester(WalkForwardConfig(n_splits=2, min_sharpe=-99, min_win_rate=0, max_drawdown=1.0))
    res = wf.run(_BadFit(), _ohlcv(40), "X")
    assert len(res.fold_results) >= 1


def test_backtest_fold_rejects_missing_ohlc_columns():
    wf = WalkForwardBacktester()
    bad = pd.DataFrame({"close": [1, 2]}, index=pd.date_range("2024-01-01", periods=2, freq="D"))
    with pytest.raises(ValueError, match="OHLCV"):
        wf._backtest_fold(_AlwaysBuyStrategy(), bad, 1, train_data=bad.iloc[:0])


# ===========================================================================
# Costs + exit logic
# ===========================================================================


def test_entry_applies_slippage_and_commission_moves_equity():
    df = _ohlcv(25)
    cfg = WalkForwardConfig(
        commission_bps=100.0,
        slippage_bps=100.0,
        initial_capital=100_000.0,
    )
    wf = WalkForwardBacktester(cfg)
    res = wf._backtest_fold(_BuyThenSellStrategy(sell_after=6), df, 1, train_data=df.iloc[:0])
    assert res.total_trades >= 1
    t0 = res.trades[0]
    slip = 0.01
    raw_entry = float(df.loc[t0["entry_time"], "close"])
    assert t0["entry_price"] == pytest.approx(raw_entry * (1 + slip), rel=0.001)


def test_exit_on_stop_loss():
    """Forced stop: buy with very high stop so first red bar hits."""
    idx = pd.date_range("2024-01-01", periods=15, freq="D", tz="UTC")
    prices = [100.0] * 3 + [95.0] * 12
    df = pd.DataFrame(
        {
            "open": prices,
            "high": [p * 1.01 for p in prices],
            "low": [p * 0.98 for p in prices],
            "close": prices,
            "volume": [1000] * 15,
        },
        index=idx,
    )

    class _S:
        name = "OneShot"
        def generate_signal(self, d: pd.DataFrame) -> StrategySignal:
            if len(d) == 3:
                return StrategySignal("buy", 1.0, 200.0, 99.0, 10, "x")
            return StrategySignal("hold", 0.5, None, None, 0, "wait")

    wf = WalkForwardBacktester(WalkForwardConfig(commission_bps=0, slippage_bps=0))
    fr = wf._backtest_fold(_S(), df, 1, train_data=df.iloc[:0])
    assert fr.total_trades >= 1
    assert fr.trades[0]["exit_price"] == pytest.approx(99.0)


def test_exit_on_take_profit():
    idx = pd.date_range("2024-01-01", periods=10, freq="D", tz="UTC")
    prices = [100, 100, 100, 110, 110, 110, 110, 110, 110, 110]
    df = pd.DataFrame(
        {
            "open": prices,
            "high": [p + 2 for p in prices],
            "low": [p - 1 for p in prices],
            "close": prices,
            "volume": [1000] * 10,
        },
        index=idx,
    )

    class _S:
        name = "TP"
        def generate_signal(self, d: pd.DataFrame) -> StrategySignal:
            if len(d) == 3:
                return StrategySignal("buy", 1.0, 108.0, 90.0, 2, "x")
            return StrategySignal("hold", 0.5, None, None, 0, "wait")

    wf = WalkForwardBacktester(WalkForwardConfig(commission_bps=0, slippage_bps=0))
    fr = wf._backtest_fold(_S(), df, 1, train_data=df.iloc[:0])
    assert fr.total_trades == 1
    assert fr.trades[0]["exit_price"] == pytest.approx(108.0)


def test_exit_on_sell_signal():
    wf = WalkForwardBacktester(WalkForwardConfig(min_sharpe=-99, min_win_rate=0, max_drawdown=1.0))
    fr = wf._backtest_fold(_BuyThenSellStrategy(sell_after=8), _ohlcv(20), 1, train_data=_ohlcv(20).iloc[:0])
    assert fr.total_trades >= 1


# ===========================================================================
# Metrics + validation + aggregation
# ===========================================================================


def test_metrics_empty_trades_all_zero():
    wf = WalkForwardBacktester()
    df = _ohlcv(5)
    m = wf._calculate_metrics([], [100_000, 100_000], df)
    assert m["sharpe"] == 0 and m["win_rate"] == 0 and m["max_drawdown"] == 0


def test_metrics_profit_factor_infinite_capped_in_aggregator():
    assert _finite_profit_factor(float("inf"), cap=12.0) == 12.0
    assert _finite_profit_factor(3.0) == 3.0


def test_validate_fails_low_sharpe():
    wf = WalkForwardBacktester(WalkForwardConfig(min_sharpe=5.0))
    ok, reason = wf._validate_results(0.1, 0.9, 0.01)
    assert ok is False and reason and "Sharpe" in reason


def test_validate_fails_low_win_rate():
    wf = WalkForwardBacktester(WalkForwardConfig(min_win_rate=0.90))
    ok, reason = wf._validate_results(5.0, 0.2, 0.01)
    assert ok is False and reason and "Win rate" in reason


def test_validate_fails_high_drawdown():
    wf = WalkForwardBacktester(WalkForwardConfig(max_drawdown=0.05))
    ok, reason = wf._validate_results(5.0, 0.90, 0.50)
    assert ok is False and reason and "DD" in reason


def test_validate_passes():
    wf = WalkForwardBacktester()
    ok, reason = wf._validate_results(2.0, 0.60, 0.05)
    assert ok is True and reason is None


def test_annualized_return_with_datetime_index():
    idx = pd.date_range("2024-01-01", periods=100, freq="D")
    ann = _annualized_return(idx, 0.10)
    assert ann > 0.10


def test_fold_result_dataclass_fields():
    fr = FoldResult(
        1, None, None, None, None, 1.0, 1.0, 1.0, 0.5, 2.0, 0.1, 5, 0.05, 0.1, []
    )
    assert fr.total_trades == 5


def test_worst_drawdown_is_max_across_folds():
    wf = WalkForwardBacktester(WalkForwardConfig(n_splits=3, min_sharpe=-99, min_win_rate=0, max_drawdown=1.0))
    res = wf.run(_AlwaysBuyStrategy(), _ohlcv(60), "X")
    assert res.worst_drawdown == max(f.max_drawdown for f in res.fold_results)


# ===========================================================================
# BrokerStopManager
# ===========================================================================


def test_broker_stop_kite_unavailable_with_none_factory():
    mgr = BrokerStopManager(kite_factory=lambda: None)
    out = mgr.place_stop_loss("RELIANCE", 1, 2500.0)
    assert out["status"] == "kite_unavailable"


def test_broker_stop_validation_empty_symbol():
    mgr = BrokerStopManager(kite_factory=lambda: None)
    assert mgr.place_stop_loss("", 1, 100.0)["status"] == "error"


def test_broker_stop_validation_bad_quantity():
    mgr = BrokerStopManager(kite_factory=lambda: None)
    assert mgr.place_stop_loss("X", 0, 100.0)["status"] == "error"


def test_broker_stop_validation_bad_trigger():
    mgr = BrokerStopManager(kite_factory=lambda: None)
    assert mgr.place_stop_loss("X", 1, 0.0)["status"] == "error"


def test_broker_stop_place_gtt_limit_success():
    kite = MagicMock()
    kite.GTT_TYPE_SINGLE = "single"
    kite.TRANSACTION_TYPE_SELL = "SELL"
    kite.ORDER_TYPE_LIMIT = "LIMIT"
    kite.ORDER_TYPE_MARKET = "MARKET"
    kite.place_gtt.return_value = {"trigger_id": 42}

    mgr = BrokerStopManager(kite_client=kite)
    out = mgr.place_stop_loss("RELIANCE", 10, 2400.0, limit_price=2395.0)

    assert out["status"] == "placed"
    assert out["trigger_id"] == 42
    kite.place_gtt.assert_called_once()
    call_kw = kite.place_gtt.call_args[1]
    assert call_kw["trigger_values"] == [2400.0]
    assert call_kw["orders"][0]["order_type"] == "LIMIT"
    assert call_kw["orders"][0]["price"] == 2395.0
    assert call_kw["orders"][0]["exchange"] == "NSE"


def test_broker_stop_place_gtt_market_without_limit():
    kite = MagicMock()
    kite.GTT_TYPE_SINGLE = "single"
    kite.TRANSACTION_TYPE_SELL = "SELL"
    kite.ORDER_TYPE_MARKET = "MARKET"
    kite.place_gtt.return_value = {"trigger_id": 7}

    mgr = BrokerStopManager(kite_client=kite)
    out = mgr.place_stop_loss("TCS", 5, 3500.0)

    assert out["status"] == "placed"
    assert kite.place_gtt.call_args[1]["orders"][0]["price"] == 0.0


def test_broker_stop_place_gtt_returns_error_on_exception():
    kite = MagicMock()
    kite.GTT_TYPE_SINGLE = "single"
    kite.TRANSACTION_TYPE_SELL = "SELL"
    kite.ORDER_TYPE_MARKET = "MARKET"
    kite.place_gtt.side_effect = RuntimeError("upstream")

    mgr = BrokerStopManager(kite_client=kite)
    out = mgr.place_stop_loss("INFY", 1, 1500.0)
    assert out["status"] == "error"
    assert "upstream" in out["error"]


def test_broker_stop_cancel_gtt():
    kite = MagicMock()
    mgr = BrokerStopManager(kite_client=kite)
    assert mgr.cancel_gtt(99)["status"] == "cancelled"
    kite.delete_gtt.assert_called_once_with(99)


def test_broker_stop_cancel_unavailable():
    mgr = BrokerStopManager(kite_factory=lambda: None)
    assert mgr.cancel_gtt(1)["status"] == "kite_unavailable"


def test_broker_sdk_available_is_bool():
    assert isinstance(BrokerStopManager.kite_sdk_available(), bool)


def test_broker_env_credentials_present_is_bool():
    assert isinstance(BrokerStopManager.env_credentials_present(), bool)


def test_calculate_metrics_sortino_when_only_losses_use_std():
    """With a single losing trade, sortino falls back like sharpe."""
    wf = WalkForwardBacktester(WalkForwardConfig(periods_per_year=252))
    df = _ohlcv(5)
    trades = [{"return_pct": -5.0}]
    eq = [100_000.0, 99_000.0]
    m = wf._calculate_metrics(trades, eq, df)
    assert m["win_rate"] == 0.0
    assert m["sharpe"] == 0.0  # one trade -> no sample std


def test_calculate_metrics_sharpe_with_multiple_trades():
    wf = WalkForwardBacktester(WalkForwardConfig(periods_per_year=252))
    df = _ohlcv(30)
    trades = [{"return_pct": 2.0}, {"return_pct": -1.0}, {"return_pct": 3.0}]
    eq = [100_000.0, 101_000.0, 100_500.0, 102_000.0]
    m = wf._calculate_metrics(trades, eq, df)
    assert m["sharpe"] != 0.0 or m["sortino"] != 0.0


def test_walk_forward_full_run_produces_timestamp():
    wf = WalkForwardBacktester(WalkForwardConfig(n_splits=3, min_sharpe=-99, min_win_rate=0, max_drawdown=1.0))
    res = wf.run(_BuyThenSellStrategy(), _ohlcv(45), "X")
    assert res.timestamp.tzinfo is not None


def test_walk_forward_config_unused_train_size_documented():
    """train_size / test_size are reserved; splits use contiguous test chunks."""
    cfg = WalkForwardConfig(train_size=0.6, test_size=0.2)
    assert cfg.train_size == 0.6
