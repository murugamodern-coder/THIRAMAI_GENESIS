"""Tests for the new pandas-DataFrame multi-strategy engine.

Note: this is the *new* strategy stack at ``services.quant.strategies.*``.
The legacy ``services.quant.backtester.RSIMACDStrategy`` (candle-list API)
has its own coverage in ``tests/test_quant_strategies.py`` and is NOT
exercised here; both stacks coexist.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from services.quant.regime_detector import RegimeDetector
from services.quant.strategies import (
    BreakoutStrategy,
    GapStrategy,
    MomentumStrategy,
    PairsStrategy,
    RSIMACDStrategy,
    StrategyBase,
    StrategyMetrics,
    StrategySignal,
    VWAPMeanReversionStrategy,
)
from services.quant.strategy_manager import (
    StrategyManager,
    get_strategy_manager,
    reset_strategy_manager,
)
from services.quant.strategy_selector import StrategySelector


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _trend_up(n: int = 60, start: float = 100.0, step: float = 1.0) -> pd.DataFrame:
    """Synthetic monotonically-rising OHLCV used to trigger trend signals."""
    closes = np.array([start + i * step for i in range(n)], dtype=float)
    return pd.DataFrame(
        {
            "open": closes - 0.2,
            "high": closes + 0.5,
            "low": closes - 0.5,
            "close": closes,
            "volume": np.full(n, 1000.0),
        }
    )


def _trend_down(n: int = 60, start: float = 100.0, step: float = 1.0) -> pd.DataFrame:
    closes = np.array([start - i * step for i in range(n)], dtype=float)
    closes = np.maximum(closes, 1.0)
    return pd.DataFrame(
        {
            "open": closes + 0.2,
            "high": closes + 0.5,
            "low": closes - 0.5,
            "close": closes,
            "volume": np.full(n, 1000.0),
        }
    )


def _ranging(n: int = 60, mid: float = 100.0, amp: float = 0.3) -> pd.DataFrame:
    """Tight sine wave around ``mid`` so 20-bar trend stays well under the
    detector's 2% threshold and annualised volatility stays modest."""
    closes = np.array([mid + amp * np.sin(i / 2.0) for i in range(n)], dtype=float)
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes + 0.05,
            "low": closes - 0.05,
            "close": closes,
            "volume": np.full(n, 1000.0),
        }
    )


def _volatile(n: int = 60, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = 100.0 * np.cumprod(1.0 + rng.normal(0, 0.04, n))
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes * 1.01,
            "low": closes * 0.99,
            "close": closes,
            "volume": np.full(n, 1000.0),
        }
    )


@pytest.fixture(autouse=True)
def _reset():
    reset_strategy_manager()
    yield
    reset_strategy_manager()


# ===========================================================================
# StrategyBase + StrategySignal + StrategyMetrics
# ===========================================================================


class _NoopStrategy(StrategyBase):
    """Concrete subclass that emits hold and a fixed regime score."""

    def generate_signal(self, data: pd.DataFrame) -> StrategySignal:
        return self._hold_signal()

    def suitable_for_regime(self, regime: str) -> float:
        return 0.5


def test_strategy_base_does_not_share_caller_params():
    user_params = {"capital": 50_000, "stage": "paper", "extra": "x"}
    strategy = _NoopStrategy(user_params)
    user_params["capital"] = 1
    assert strategy.params["capital"] == 50_000


def test_strategy_base_invalid_stage_falls_back_to_paper():
    s = _NoopStrategy({"stage": "wonderland"})
    assert s.stage == "paper"


def test_strategy_signal_as_dict_round_trip():
    sig = StrategySignal(
        action="buy", confidence=0.5, price_target=100.0, stop_loss=95.0,
        quantity=10, reasoning="test",
    )
    d = sig.as_dict()
    assert d["action"] == "buy" and d["quantity"] == 10
    assert "timestamp" in d


def test_calculate_quantity_handles_invalid_price():
    s = _NoopStrategy({"capital": 100_000})
    assert s._calculate_quantity(0) == 0
    assert s._calculate_quantity(-5) == 0
    assert s._calculate_quantity(float("inf")) == 0


def test_calculate_quantity_clamps_allocation():
    s = _NoopStrategy({"capital": 100_000})
    # Default 10% of 100k at price 100 -> 100 shares
    assert s._calculate_quantity(100.0) == 100
    # Out-of-range allocation_pct is clamped; 5.0 -> 1.0
    assert s._calculate_quantity(100.0, allocation_pct=5.0) == 1000


def test_metrics_blank_when_no_trades():
    s = _NoopStrategy()
    assert s.metrics.total_trades == 0
    assert s.metrics.max_drawdown == 0.0


def test_update_metrics_computes_win_rate_and_pf():
    s = _NoopStrategy()
    s.update_metrics({"pnl": 100.0, "return_pct": 0.05})
    s.update_metrics({"pnl": -50.0, "return_pct": -0.02})
    s.update_metrics({"pnl": 80.0, "return_pct": 0.04})
    assert s.metrics.total_trades == 3
    assert s.metrics.win_rate == pytest.approx(2 / 3)
    assert s.metrics.profit_factor == pytest.approx(180.0 / 50.0)


def test_update_metrics_drawdown_handles_negative_running_max():
    """Original spec divided by running_max which is wrong when the running
    peak is non-positive (e.g. first trade is a loss). We use absolute
    peak-trough magnitude so this case is well-defined."""
    s = _NoopStrategy()
    s.update_metrics({"pnl": -100.0})
    s.update_metrics({"pnl": -50.0})  # drawdown deepens
    # Running max = [-100, -100], cumulative = [-100, -150], drawdown = [0, 50]
    assert s.metrics.max_drawdown == pytest.approx(50.0)


def test_update_metrics_drawdown_zero_for_monotone_gains():
    s = _NoopStrategy()
    for pnl in [10.0, 20.0, 30.0]:
        s.update_metrics({"pnl": pnl})
    assert s.metrics.max_drawdown == 0.0


def test_update_metrics_sharpe_zero_when_returns_constant():
    s = _NoopStrategy()
    for _ in range(5):
        s.update_metrics({"pnl": 1.0, "return_pct": 0.01})
    assert s.metrics.sharpe_ratio == 0.0


def test_update_metrics_profit_factor_inf_when_no_losses():
    s = _NoopStrategy()
    s.update_metrics({"pnl": 100.0})
    assert s.metrics.profit_factor == float("inf")


def test_can_trade_paper_and_shadow_always_pass():
    paper = _NoopStrategy({"stage": "paper"})
    shadow = _NoopStrategy({"stage": "shadow"})
    assert paper.can_trade()
    assert shadow.can_trade()


def test_can_trade_canary_blocked_until_min_trades():
    canary = _NoopStrategy({"stage": "canary"})
    canary.metrics.sharpe_ratio = 99.0  # huge sharpe but no trades
    assert canary.can_trade() is False  # min_trades guard


def test_can_trade_live_requires_winrate_and_sharpe():
    live = _NoopStrategy({"stage": "live", "min_trades_for_promotion": 5})
    # Manufacture metrics state
    live.metrics.total_trades = 30
    live.metrics.sharpe_ratio = 2.0
    live.metrics.win_rate = 0.50
    assert live.can_trade()
    live.metrics.win_rate = 0.40
    assert not live.can_trade()
    live.metrics.win_rate = 0.50
    live.metrics.sharpe_ratio = 1.0
    assert not live.can_trade()


# ===========================================================================
# BreakoutStrategy
# ===========================================================================


def test_breakout_emits_buy_on_new_high():
    data = _trend_up(n=30)
    sig = BreakoutStrategy({"capital": 100_000, "lookback": 20}).generate_signal(data)
    assert sig.action == "buy"
    assert sig.price_target is not None and sig.price_target > sig.stop_loss
    assert sig.quantity > 0


def test_breakout_holds_in_ranging_market():
    data = _ranging(n=30)
    sig = BreakoutStrategy({"capital": 100_000}).generate_signal(data)
    assert sig.action == "hold"


def test_breakout_holds_with_insufficient_data():
    data = _trend_up(n=10)
    sig = BreakoutStrategy({"capital": 100_000}).generate_signal(data)
    assert sig.action == "hold"


def test_breakout_regime_suitability():
    s = BreakoutStrategy({})
    assert s.suitable_for_regime("trending_up") > s.suitable_for_regime("ranging")


# ===========================================================================
# VWAPMeanReversionStrategy
# ===========================================================================


def test_vwap_buys_when_price_below_vwap():
    closes = np.full(30, 100.0)
    closes[-1] = 95.0  # 5% below VWAP
    data = pd.DataFrame({
        "close": closes,
        "volume": np.full(30, 1000.0),
        "open": closes, "high": closes + 0.1, "low": closes - 0.1,
    })
    sig = VWAPMeanReversionStrategy({"capital": 100_000}).generate_signal(data)
    assert sig.action == "buy"


def test_vwap_sells_when_price_above_vwap():
    closes = np.full(30, 100.0)
    closes[-1] = 105.0
    data = pd.DataFrame({
        "close": closes, "volume": np.full(30, 1000.0),
        "open": closes, "high": closes + 0.1, "low": closes - 0.1,
    })
    sig = VWAPMeanReversionStrategy({"capital": 100_000}).generate_signal(data)
    assert sig.action == "sell"


def test_vwap_holds_when_price_near_vwap():
    closes = np.full(30, 100.0)
    closes[-1] = 100.5
    data = pd.DataFrame({"close": closes, "volume": np.full(30, 1000.0),
                         "open": closes, "high": closes, "low": closes})
    sig = VWAPMeanReversionStrategy({"capital": 100_000}).generate_signal(data)
    assert sig.action == "hold"


def test_vwap_handles_zero_volume_without_dividing_by_zero():
    closes = np.full(30, 100.0)
    data = pd.DataFrame({"close": closes, "volume": np.zeros(30),
                         "open": closes, "high": closes, "low": closes})
    sig = VWAPMeanReversionStrategy({"capital": 100_000}).generate_signal(data)
    assert sig.action == "hold"
    assert "VWAP" in sig.reasoning


# ===========================================================================
# MomentumStrategy + RSI
# ===========================================================================


def test_momentum_emits_buy_in_strong_uptrend():
    """A perfect monotone rise gives RSI=100 (no losses) and the strategy
    correctly refuses to chase. We relax the overbought threshold here so
    the buy condition hinges purely on the momentum gate."""
    data = _trend_up(n=30)
    sig = MomentumStrategy(
        {"capital": 100_000, "rsi_overbought": 101}
    ).generate_signal(data)
    assert sig.action == "buy"


def test_momentum_holds_in_ranging_market():
    data = _ranging(n=60)
    sig = MomentumStrategy({"capital": 100_000}).generate_signal(data)
    assert sig.action == "hold"


def test_momentum_rsi_returns_100_when_no_losses():
    # Pure uptrend - all positive deltas
    closes = pd.Series([100.0 + i for i in range(20)])
    rsi = MomentumStrategy._rsi(closes, period=14)
    assert rsi == pytest.approx(100.0)


def test_momentum_rsi_returns_50_for_flat_series():
    closes = pd.Series([100.0] * 20)
    rsi = MomentumStrategy._rsi(closes, period=14)
    # avg_gain=0 and avg_loss=0 -> we return 50 (no information)
    assert rsi == pytest.approx(50.0)


# ===========================================================================
# GapStrategy
# ===========================================================================


def test_gap_strategy_fades_gap_up():
    closes = [100.0] * 5
    opens = [100.0] * 4 + [105.0]  # 5% gap up on the latest bar
    data = pd.DataFrame({
        "open": opens,
        "close": closes,
        "high": [c + 1 for c in closes],
        "low": [c - 1 for c in closes],
        "volume": [1000.0] * 5,
    })
    sig = GapStrategy({"capital": 100_000}).generate_signal(data)
    assert sig.action == "sell"
    assert "gap up" in sig.reasoning.lower()


def test_gap_strategy_fades_gap_down():
    closes = [100.0] * 5
    opens = [100.0] * 4 + [95.0]  # 5% gap down
    data = pd.DataFrame({
        "open": opens, "close": closes,
        "high": [c + 1 for c in closes], "low": [c - 1 for c in closes],
        "volume": [1000.0] * 5,
    })
    sig = GapStrategy({"capital": 100_000}).generate_signal(data)
    assert sig.action == "buy"


def test_gap_strategy_holds_for_small_gap():
    closes = [100.0] * 5
    opens = [100.0] * 4 + [100.5]  # 0.5% gap - below threshold
    data = pd.DataFrame({
        "open": opens, "close": closes,
        "high": closes, "low": closes, "volume": [1000.0] * 5,
    })
    sig = GapStrategy({"capital": 100_000}).generate_signal(data)
    assert sig.action == "hold"


# ===========================================================================
# PairsStrategy
# ===========================================================================


def test_pairs_holds_when_no_secondary_supplied():
    data = _trend_up(n=40)
    sig = PairsStrategy({"capital": 100_000}).generate_signal(data)
    assert sig.action == "hold"
    assert "secondary" in sig.reasoning


def test_pairs_emits_signal_when_spread_extreme():
    n = 50
    primary = pd.Series([100.0 + 0.1 * i for i in range(n)])
    secondary = pd.Series([100.0 + 0.1 * i for i in range(n)])
    primary.iloc[-1] = primary.iloc[-1] + 10  # blow out the spread
    data = pd.DataFrame({
        "open": primary, "high": primary, "low": primary,
        "close": primary, "volume": np.full(n, 1000.0),
    })
    sig = PairsStrategy({"capital": 100_000, "secondary_series": secondary, "window": 30}).generate_signal(data)
    assert sig.action in ("sell", "buy")


def test_pairs_holds_for_in_band_spread():
    n = 50
    primary = pd.Series([100.0 + 0.1 * i for i in range(n)])
    secondary = pd.Series([100.0 + 0.1 * i for i in range(n)])
    data = pd.DataFrame({
        "open": primary, "high": primary, "low": primary,
        "close": primary, "volume": np.full(n, 1000.0),
    })
    sig = PairsStrategy({"capital": 100_000, "secondary_series": secondary}).generate_signal(data)
    assert sig.action == "hold"


# ===========================================================================
# RSIMACDStrategy (new pandas version)
# ===========================================================================


def test_rsi_macd_holds_with_insufficient_history():
    sig = RSIMACDStrategy({"capital": 100_000}).generate_signal(_trend_up(n=10))
    assert sig.action == "hold"


def test_rsi_macd_runs_on_trending_data_without_error():
    sig = RSIMACDStrategy({"capital": 100_000}).generate_signal(_trend_up(n=80))
    # Action depends on signal/cross detection - just verify shape.
    assert sig.action in {"buy", "sell", "hold"}
    assert isinstance(sig.confidence, float)


def test_rsi_macd_regime_suitability_prefers_trends():
    s = RSIMACDStrategy({})
    assert s.suitable_for_regime("trending_up") >= s.suitable_for_regime("ranging")


# ===========================================================================
# RegimeDetector (rule-based path)
# ===========================================================================


@pytest.fixture()
def fallback_detector() -> RegimeDetector:
    return RegimeDetector(force_fallback=True)


def test_regime_unknown_for_short_series(fallback_detector):
    out = fallback_detector.detect(pd.Series([1.0, 2.0, 3.0]))
    assert out["regime"] == "unknown"


def test_regime_trending_up_on_monotone_rise(fallback_detector):
    prices = _trend_up(n=60)["close"]
    out = fallback_detector.detect(prices)
    assert out["regime"] == "trending_up"


def test_regime_trending_down_on_monotone_fall(fallback_detector):
    prices = _trend_down(n=60)["close"]
    out = fallback_detector.detect(prices)
    assert out["regime"] == "trending_down"


def test_regime_ranging_on_flat_series(fallback_detector):
    prices = _ranging(n=60)["close"]
    out = fallback_detector.detect(prices)
    assert out["regime"] == "ranging"


def test_regime_volatile_on_noisy_series(fallback_detector):
    prices = _volatile(n=60)["close"]
    out = fallback_detector.detect(prices)
    assert out["regime"] == "volatile"


def test_regime_detector_using_hmm_property(fallback_detector):
    assert fallback_detector.using_hmm is False


# ===========================================================================
# StrategySelector
# ===========================================================================


def _selector(strategies=None) -> StrategySelector:
    if strategies is None:
        strategies = [BreakoutStrategy({}), VWAPMeanReversionStrategy({})]
    return StrategySelector(strategies, regime_detector=RegimeDetector(force_fallback=True))


def test_selector_requires_at_least_one_strategy():
    with pytest.raises(ValueError):
        StrategySelector([])


def test_selector_picks_breakout_in_uptrend():
    sel = _selector()
    chosen = sel.select(_trend_up(n=60)["close"])
    assert chosen.name == "BreakoutStrategy"


def test_selector_picks_mean_reversion_in_ranging_market():
    sel = _selector()
    chosen = sel.select(_ranging(n=60)["close"])
    assert chosen.name == "VWAPMeanReversionStrategy"


def test_selector_clamps_negative_sharpe_in_score():
    """A strategy with negative Sharpe must not be penalised below the
    'no-track-record' baseline (the original spec allowed it)."""
    s_bad = BreakoutStrategy({})
    s_bad.metrics.sharpe_ratio = -5.0
    s_bad.metrics.total_trades = 100
    selector = StrategySelector([s_bad], regime_detector=RegimeDetector(force_fallback=True))
    explanations = selector.explain("trending_up")
    # Score = 0.7 * 0.9 + 0.3 * 0.0 = 0.63
    assert explanations[0]["score"] == pytest.approx(0.63)


def test_selector_can_trade_filter_falls_back_when_empty():
    """If require_can_trade=True returns nothing (e.g. all canary stage),
    the selector must still produce a winner."""
    canary = BreakoutStrategy({"stage": "canary"})
    selector = StrategySelector([canary], regime_detector=RegimeDetector(force_fallback=True))
    chosen = selector.select(_trend_up(n=60)["close"], require_can_trade=True)
    assert chosen is canary


def test_selector_explain_lists_all_strategies():
    sel = _selector()
    out = sel.explain("trending_up")
    assert len(out) == 2
    assert {row["name"] for row in out} == {"BreakoutStrategy", "VWAPMeanReversionStrategy"}


# ===========================================================================
# StrategyManager
# ===========================================================================


def test_manager_default_registers_six_strategies():
    mgr = StrategyManager()
    assert len(mgr) == 6
    expected = {"breakout", "mean_reversion", "momentum", "gap", "pairs", "rsi_macd"}
    assert set(mgr.names()) == expected


def test_manager_get_returns_none_for_missing():
    mgr = StrategyManager()
    assert mgr.get("nope") is None


def test_manager_get_or_raise_raises_for_missing():
    mgr = StrategyManager()
    with pytest.raises(KeyError):
        mgr.get_or_raise("nope")


def test_manager_register_replaces_existing():
    mgr = StrategyManager()
    new_breakout = BreakoutStrategy({"capital": 999_999})
    mgr.register("breakout", new_breakout)
    assert mgr.get("breakout") is new_breakout


def test_manager_unregister_returns_bool():
    mgr = StrategyManager()
    assert mgr.unregister("breakout") is True
    assert mgr.unregister("breakout") is False


def test_manager_get_by_stage_filters_correctly():
    mgr = StrategyManager(register_defaults=False)
    mgr.register("p", BreakoutStrategy({"stage": "paper"}))
    mgr.register("c", BreakoutStrategy({"stage": "canary"}))
    assert len(mgr.get_by_stage("paper")) == 1
    assert len(mgr.get_by_stage("canary")) == 1
    assert len(mgr.get_by_stage("live")) == 0


def test_manager_register_validates_inputs():
    mgr = StrategyManager(register_defaults=False)
    with pytest.raises(ValueError):
        mgr.register("", BreakoutStrategy({}))
    with pytest.raises(TypeError):
        mgr.register("x", "not_a_strategy")  # type: ignore[arg-type]


def test_manager_singleton_returns_same_instance():
    a = get_strategy_manager()
    b = get_strategy_manager()
    assert a is b


def test_manager_singleton_resets():
    a = get_strategy_manager()
    reset_strategy_manager()
    b = get_strategy_manager()
    assert a is not b


def test_manager_tradable_only_returns_can_trade():
    mgr = StrategyManager(register_defaults=False)
    paper = BreakoutStrategy({"stage": "paper"})
    canary_no_trades = BreakoutStrategy({"stage": "canary"})
    mgr.register("paper", paper)
    mgr.register("canary", canary_no_trades)
    tradable = mgr.tradable()
    assert paper in tradable
    assert canary_no_trades not in tradable


# ===========================================================================
# End-to-end smoke
# ===========================================================================


def test_end_to_end_select_and_signal_in_uptrend():
    mgr = StrategyManager()
    selector = StrategySelector(
        mgr.get_all(),
        regime_detector=RegimeDetector(force_fallback=True),
    )
    data = _trend_up(n=80)
    chosen = selector.select(data["close"])
    signal = chosen.generate_signal(data)
    # We don't assert a specific action - just that the pipeline produces
    # a valid signal end-to-end.
    assert signal.action in {"buy", "sell", "hold"}
    assert isinstance(signal, StrategySignal)
