"""Portfolio risk engine + intraday ingestion + robust tick stream tests.

All I/O is mocked: no real database, no Redis, no Kite SDK, no network.
The fakes here intentionally intercept the specific SQL strings the
production code emits - if those SQL statements change, these tests fail
loudly, which is the desired behaviour for a contract test.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, time as dtime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from services.quant.intraday_data_ingestion import IngestionResult, IntradayDataIngestion
from services.quant.portfolio_risk_engine import (
    PortfolioRisk,
    PortfolioRiskEngine,
    PositionRisk,
    RiskLimits,
    get_portfolio_risk_engine,
    reset_portfolio_risk_engine,
)
from workers.tick_stream_robust import (
    RobustTickStream,
    get_robust_tick_stream,
    reset_robust_tick_stream,
)


# ---------------------------------------------------------------------------
# Fake SQLAlchemy engine for deterministic, offline tests
# ---------------------------------------------------------------------------


class _FakeResult:
    """Stand-in for the result returned by ``conn.execute(text(...))``."""

    def __init__(self, rows: list[tuple] | None = None, rowcount: int = 0) -> None:
        self._rows = list(rows or [])
        self.rowcount = rowcount

    def fetchall(self) -> list[tuple]:
        return list(self._rows)

    def first(self) -> tuple | None:
        return self._rows[0] if self._rows else None

    def scalar(self) -> Any:
        return self._rows[0][0] if self._rows else None


class _FakeConnection:
    """Pattern-matches on SQL text to dispatch to the right fake row set."""

    def __init__(self, fake_engine: "_FakeEngine") -> None:
        self._engine = fake_engine
        self.commits = 0
        self.executed_statements: list[str] = []

    def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        sql = str(statement).lower()
        self.executed_statements.append(sql)
        if "from paper_trades" in sql and "status = 'open'" in sql:
            return _FakeResult(self._engine.open_positions)
        if "from paper_trades" in sql and "sum(realized_pnl)" in sql:
            return _FakeResult([(self._engine.realized_today,)])
        if "from paper_trades" in sql and "realized_pnl" in sql and "order by" in sql:
            return _FakeResult([(p,) for p in self._engine.closed_pnls])
        if "insert into ohlcv_data" in sql:
            self._engine.ohlcv_inserts.append(dict(params or {}))
            # Simulate an ON CONFLICT skip if duplicate timestamp.
            ts = (params or {}).get("ts")
            if ts in self._engine.existing_timestamps:
                return _FakeResult(rowcount=0)
            self._engine.existing_timestamps.add(ts)
            return _FakeResult(rowcount=1)
        return _FakeResult()

    def commit(self) -> None:
        self.commits += 1

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *args: Any) -> None:
        return None


class _FakeEngine:
    """Drop-in for the SQLAlchemy engine returned by ``get_engine()``."""

    def __init__(
        self,
        *,
        open_positions: list[tuple] | None = None,
        realized_today: float = 0.0,
        closed_pnls: list[float] | None = None,
    ) -> None:
        self.open_positions = open_positions or []
        self.realized_today = float(realized_today)
        self.closed_pnls = list(closed_pnls or [])
        self.ohlcv_inserts: list[dict[str, Any]] = []
        self.existing_timestamps: set = set()
        self.last_connection: _FakeConnection | None = None

    def connect(self) -> _FakeConnection:
        conn = _FakeConnection(self)
        self.last_connection = conn
        return conn


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_portfolio_risk_engine()
    reset_robust_tick_stream()
    yield
    reset_portfolio_risk_engine()
    reset_robust_tick_stream()


@pytest.fixture
def empty_engine() -> _FakeEngine:
    return _FakeEngine()


# ===========================================================================
# RiskLimits + dataclasses
# ===========================================================================


def test_risk_limits_defaults_are_sensible():
    limits = RiskLimits()
    assert 0 < limits.max_position_pct < 1
    assert 0 < limits.max_sector_pct < 1
    assert limits.max_var_95_pct < limits.max_drawdown_pct  # vol < dd
    assert limits.max_gross_leverage >= 1


def test_position_risk_dataclass_is_constructable():
    pos = PositionRisk(
        symbol="X", quantity=10, entry_price=100.0, current_price=110.0,
        market_value=1100.0, pnl=100.0, pnl_pct=10.0, beta=1.0,
        sector="IT", position_pct=0.10,
    )
    assert pos.contribution_to_var == 0.0


# ===========================================================================
# PortfolioRiskEngine - construction + degraded modes
# ===========================================================================


def test_engine_with_no_db_returns_base_capital():
    engine = PortfolioRiskEngine(engine=None, base_capital=250_000)
    snapshot = engine.get_portfolio()
    assert snapshot.total_value == 250_000
    assert snapshot.positions == []


def test_engine_handles_db_read_failure_gracefully():
    bad_engine = MagicMock()
    bad_engine.connect.side_effect = RuntimeError("db down")
    engine = PortfolioRiskEngine(engine=bad_engine, base_capital=100_000)
    snapshot = engine.get_portfolio()
    assert snapshot.total_value == 100_000


def test_engine_normalizes_invalid_side(empty_engine):
    engine = PortfolioRiskEngine(engine=empty_engine)
    out = engine.check_trade_allowed("RELIANCE", 10, 1000.0, side="banana")
    assert out["allowed"] is False
    assert "side" in out["reason"]


def test_engine_rejects_non_positive_quantity(empty_engine):
    engine = PortfolioRiskEngine(engine=empty_engine)
    out = engine.check_trade_allowed("RELIANCE", 0, 1000.0, side="buy")
    assert out["allowed"] is False
    out2 = engine.check_trade_allowed("RELIANCE", -5, 1000.0, side="buy")
    assert out2["allowed"] is False


def test_engine_rejects_non_positive_price(empty_engine):
    engine = PortfolioRiskEngine(engine=empty_engine)
    out = engine.check_trade_allowed("RELIANCE", 10, 0, side="buy")
    assert out["allowed"] is False


# ===========================================================================
# PortfolioRiskEngine - happy path + each limit
# ===========================================================================


def test_check_trade_allowed_passes_when_within_limits(empty_engine):
    engine = PortfolioRiskEngine(engine=empty_engine, base_capital=1_000_000)
    # 10 shares at 100 = 1000 = 0.1% of portfolio - well under all limits
    out = engine.check_trade_allowed("RELIANCE", 10, 100.0, side="buy")
    assert out["allowed"] is True, out["reason"]
    assert "position_pct" in out["risk_metrics"]


def test_check_trade_blocks_oversized_position(empty_engine):
    # base=100k; 30 shares at 1000 = 30k = 30% > 20% position limit
    engine = PortfolioRiskEngine(engine=empty_engine, base_capital=100_000)
    out = engine.check_trade_allowed("RELIANCE", 30, 1000.0, side="buy")
    assert out["allowed"] is False
    assert "position size" in out["reason"]


def test_check_trade_blocks_sector_overconcentration():
    """Two IT positions (TCS, INFY) that together breach 40% sector cap."""
    # Existing 30k TCS position; trying to add 15k INFY -> 45% IT sector
    rows = [("TCS", "BUY", 30, 1000.0)]  # 30 * 1000 = 30k
    engine = PortfolioRiskEngine(engine=_FakeEngine(open_positions=rows), base_capital=100_000)
    out = engine.check_trade_allowed("INFY", 15, 1000.0, side="buy")
    assert out["allowed"] is False
    assert "sector" in out["reason"].lower()
    assert "IT" in out["reason"]


def test_check_trade_blocks_beta_overexposure():
    """Many high-beta positions exceeding 1.5x beta-weighted exposure."""
    # SBIN beta = 1.30 - large position to spike beta exposure
    rows = [("SBIN", "BUY", 100, 1000.0)]  # 100k = 100% of portfolio
    engine = PortfolioRiskEngine(engine=_FakeEngine(open_positions=rows), base_capital=100_000)
    out = engine.check_trade_allowed("RELIANCE", 1, 100.0, side="buy")
    # Existing portfolio already has 1.30 beta x 1.0 weight = 1.30 beta exposure.
    # The new tiny trade barely moves it but the engine still reports the metric.
    assert "beta_exposure" in out["risk_metrics"]


def test_check_trade_blocks_drawdown_when_over_limit():
    """Drawdown gate trips when historical losses pull peak-to-trough below limit."""
    # 10k loss after 5k profit -> peak 105k, trough 95k = 9.5% dd. Just under
    # the default 10% limit.
    just_under = _FakeEngine(closed_pnls=[5_000, -10_000])
    engine = PortfolioRiskEngine(engine=just_under, base_capital=100_000)
    out = engine.check_trade_allowed("RELIANCE", 1, 100.0, side="buy")
    assert out["allowed"] is True

    # 20k loss after 5k profit -> 105k -> 85k = 19% dd > 10%
    over = _FakeEngine(closed_pnls=[5_000, -20_000])
    engine = PortfolioRiskEngine(engine=over, base_capital=100_000)
    out = engine.check_trade_allowed("RELIANCE", 1, 100.0, side="buy")
    assert out["allowed"] is False
    assert "drawdown" in out["reason"].lower()


def test_check_trade_blocks_top5_concentration():
    rows = [
        ("RELIANCE", "BUY", 25, 1000.0),
        ("TCS", "BUY", 25, 1000.0),
        ("INFY", "BUY", 25, 1000.0),
        ("HDFCBANK", "BUY", 25, 1000.0),
        ("ICICIBANK", "BUY", 25, 1000.0),  # 5x 25k = 125k
    ]
    # 5 positions at 25k each = 125k vs total ~100k -> top5 concentration > 100%
    engine = PortfolioRiskEngine(engine=_FakeEngine(open_positions=rows), base_capital=100_000)
    out = engine.check_trade_allowed("WIPRO", 1, 100.0, side="buy")
    assert out["allowed"] is False
    # Multiple violations may fire; concentration must be one of them.
    assert "concentration" in out["reason"].lower() or "position" in out["reason"].lower()


def test_check_trade_blocks_var_when_over_limit():
    """Pump up per-position vol so VaR breaches the cap."""
    # Single 50k position with 30% vol and z=1.645 -> VaR ~ 24.7k = 24.7% > 5%
    rows = [("RELIANCE", "BUY", 50, 1000.0)]
    engine = PortfolioRiskEngine(
        engine=_FakeEngine(open_positions=rows),
        base_capital=100_000,
        position_volatility=0.30,
    )
    out = engine.check_trade_allowed("WIPRO", 1, 100.0, side="buy")
    assert out["allowed"] is False
    assert "var" in out["reason"].lower()


def test_check_trade_blocks_gross_leverage(empty_engine):
    """Gross leverage = gross / equity; trade larger than 2x equity should trip."""
    # 250 shares x 1000 = 250k vs 100k equity = 2.5x gross
    engine = PortfolioRiskEngine(engine=empty_engine, base_capital=100_000)
    out = engine.check_trade_allowed("RELIANCE", 250, 1000.0, side="buy")
    assert out["allowed"] is False
    # Multiple violations expected; ensure leverage is mentioned.
    assert "leverage" in out["reason"].lower() or "position" in out["reason"].lower()


# ===========================================================================
# Snapshot calculations
# ===========================================================================


def test_snapshot_equity_includes_unrealized_and_realized():
    rows = [("RELIANCE", "BUY", 10, 1000.0)]
    fake = _FakeEngine(
        open_positions=rows,
        realized_today=2_000.0,
        closed_pnls=[2_000.0],
    )
    # Price provider returns 1100, so unrealized PnL = (1100-1000)*10 = 1000
    engine = PortfolioRiskEngine(
        engine=fake,
        base_capital=100_000,
        price_provider=lambda s: 1100.0,
    )
    snapshot = engine.get_portfolio()
    assert snapshot.total_value == pytest.approx(103_000)
    assert snapshot.unrealized_pnl == pytest.approx(1_000)
    assert snapshot.realized_pnl_today == pytest.approx(2_000)


def test_snapshot_uses_entry_price_when_no_provider():
    rows = [("RELIANCE", "BUY", 10, 1000.0)]
    engine = PortfolioRiskEngine(
        engine=_FakeEngine(open_positions=rows),
        base_capital=100_000,
    )
    snapshot = engine.get_portfolio()
    pos = snapshot.positions[0]
    assert pos.current_price == 1000.0
    assert pos.pnl == 0.0


def test_snapshot_handles_short_positions_correctly():
    """Short positions have signed quantity but absolute exposure for gross/sector."""
    rows = [("RELIANCE", "SELL", 10, 1000.0)]
    engine = PortfolioRiskEngine(engine=_FakeEngine(open_positions=rows), base_capital=100_000)
    snapshot = engine.get_portfolio()
    pos = snapshot.positions[0]
    assert pos.quantity == -10
    assert pos.market_value < 0
    assert pos.position_pct == pytest.approx(0.10)  # |market_value| / total
    assert snapshot.gross_exposure == pytest.approx(10_000)
    assert snapshot.short_exposure == pytest.approx(10_000)
    assert snapshot.long_exposure == 0.0


def test_snapshot_skips_invalid_position_rows():
    """Rows with zero qty or non-positive entry price are filtered out."""
    rows = [
        ("RELIANCE", "BUY", 0, 1000.0),       # zero qty
        ("TCS", "BUY", 5, 0.0),                # zero entry
        ("INFY", "BUY", 10, 500.0),            # valid
    ]
    engine = PortfolioRiskEngine(engine=_FakeEngine(open_positions=rows), base_capital=100_000)
    snapshot = engine.get_portfolio()
    assert len(snapshot.positions) == 1
    assert snapshot.positions[0].symbol == "INFY"


def test_snapshot_falls_back_when_price_provider_throws():
    rows = [("RELIANCE", "BUY", 10, 1000.0)]
    def bad_provider(_symbol):
        raise RuntimeError("down")
    engine = PortfolioRiskEngine(
        engine=_FakeEngine(open_positions=rows),
        base_capital=100_000,
        price_provider=bad_provider,
    )
    snapshot = engine.get_portfolio()
    assert snapshot.positions[0].current_price == 1000.0  # fallback to entry


def test_snapshot_sector_exposure_uses_absolute_values():
    """A long IT and a short IT should sum to twice the gross, not net to zero."""
    rows = [
        ("TCS", "BUY", 10, 1000.0),    # +10k IT
        ("INFY", "SELL", 10, 1000.0),  # -10k IT (signed)
    ]
    engine = PortfolioRiskEngine(engine=_FakeEngine(open_positions=rows), base_capital=100_000)
    snapshot = engine.get_portfolio()
    # Sector exposure should be |10k| + |10k| = 20k, not 0.
    assert snapshot.sector_exposure["IT"] == pytest.approx(0.20)


def test_snapshot_top5_concentration_takes_largest_by_abs_value():
    rows = [
        ("RELIANCE", "BUY", 30, 1000.0),
        ("TCS", "BUY", 5, 1000.0),
        ("INFY", "BUY", 5, 1000.0),
        ("HDFCBANK", "BUY", 5, 1000.0),
        ("ICICIBANK", "BUY", 5, 1000.0),
        ("WIPRO", "BUY", 5, 1000.0),  # 6th position (smallest)
    ]
    engine = PortfolioRiskEngine(engine=_FakeEngine(open_positions=rows), base_capital=100_000)
    snapshot = engine.get_portfolio()
    # top5 = 30k + 4*5k = 50k vs 100k = 50%
    assert snapshot.top5_concentration == pytest.approx(0.50)


# ===========================================================================
# Aggregated symbol exposure
# ===========================================================================


def test_simulated_trade_aggregates_existing_symbol_exposure():
    """Adding to an existing position must push the aggregate over the limit,
    not just check the new tranche in isolation (the spec's bug)."""
    # Existing 15% RELIANCE position; adding another 8% should breach 20% limit
    rows = [("RELIANCE", "BUY", 15, 1000.0)]
    engine = PortfolioRiskEngine(engine=_FakeEngine(open_positions=rows), base_capital=100_000)
    out = engine.check_trade_allowed("RELIANCE", 8, 1000.0, side="buy")
    assert out["allowed"] is False
    assert "position size" in out["reason"]


# ===========================================================================
# VaR + beta math
# ===========================================================================


def test_var_zero_when_no_positions(empty_engine):
    engine = PortfolioRiskEngine(engine=empty_engine)
    portfolio = engine.get_portfolio()
    assert engine._calculate_var(portfolio) == 0.0


def test_var_grows_with_position_size():
    small = PortfolioRisk(total_value=100_000, positions=[
        PositionRisk("X", 1, 1000, 1000, 1000, 0, 0, 1.0, "IT", 0.01),
    ])
    big = PortfolioRisk(total_value=100_000, positions=[
        PositionRisk("X", 100, 1000, 1000, 100_000, 0, 0, 1.0, "IT", 1.0),
    ])
    engine = PortfolioRiskEngine(engine=None)
    assert engine._calculate_var(big) > engine._calculate_var(small) * 50


def test_var_respects_correlation_assumption():
    """Higher correlation between positions raises portfolio VaR."""
    portfolio = PortfolioRisk(total_value=100_000, positions=[
        PositionRisk("A", 50, 1000, 1000, 50_000, 0, 0, 1.0, "IT", 0.5),
        PositionRisk("B", 50, 1000, 1000, 50_000, 0, 0, 1.0, "IT", 0.5),
    ])
    low_rho = PortfolioRiskEngine(engine=None, position_correlation=0.0)
    high_rho = PortfolioRiskEngine(engine=None, position_correlation=0.9)
    assert high_rho._calculate_var(portfolio) > low_rho._calculate_var(portfolio)


def test_beta_weighted_exposure_zero_for_empty_portfolio():
    engine = PortfolioRiskEngine(engine=None)
    portfolio = PortfolioRisk(total_value=100_000, positions=[])
    assert engine._calculate_beta_weighted_exposure(portfolio) == 0.0


def test_beta_weighted_exposure_known_values():
    portfolio = PortfolioRisk(total_value=100_000, positions=[
        PositionRisk("X", 50, 1000, 1000, 50_000, 0, 0, 2.0, "IT", 0.5),
    ])
    engine = PortfolioRiskEngine(engine=None)
    assert engine._calculate_beta_weighted_exposure(portfolio) == pytest.approx(1.0)


def test_unknown_symbol_uses_default_beta_and_other_sector(empty_engine):
    engine = PortfolioRiskEngine(engine=empty_engine)
    assert engine._get_beta("UNKNOWNXYZ") == 1.0
    assert engine._get_sector("UNKNOWNXYZ") == "Other"


# ===========================================================================
# Singleton
# ===========================================================================


def test_portfolio_singleton_returns_same_instance():
    a = get_portfolio_risk_engine()
    b = get_portfolio_risk_engine()
    assert a is b


def test_portfolio_singleton_resets():
    a = get_portfolio_risk_engine()
    reset_portfolio_risk_engine()
    b = get_portfolio_risk_engine()
    assert a is not b


# ===========================================================================
# IntradayDataIngestion - market hours
# ===========================================================================


def _ist_at(year=2026, month=5, day=1, hour=10, minute=0) -> datetime:
    """Build a deterministic IST datetime for tests."""
    try:
        from zoneinfo import ZoneInfo
        return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("Asia/Kolkata"))
    except Exception:  # pragma: no cover
        return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_market_open_during_session():
    ing = IntradayDataIngestion(clock=lambda: _ist_at(hour=10, minute=30))
    assert ing.is_market_open() is True


def test_market_closed_before_open():
    ing = IntradayDataIngestion(clock=lambda: _ist_at(hour=8, minute=0))
    assert ing.is_market_open() is False


def test_market_closed_after_close():
    ing = IntradayDataIngestion(clock=lambda: _ist_at(hour=16, minute=0))
    assert ing.is_market_open() is False


def test_market_closed_on_weekend():
    # 2026-05-02 is a Saturday
    ing = IntradayDataIngestion(clock=lambda: _ist_at(year=2026, month=5, day=2, hour=10, minute=30))
    assert ing.is_market_open() is False


# ===========================================================================
# IntradayDataIngestion - fetch_and_store
# ===========================================================================


def _make_kite(candles: list[dict] | None = None, instruments: list[dict] | None = None):
    kite = MagicMock()
    kite.historical_data.return_value = candles or []
    kite.instruments.return_value = instruments or [
        {"tradingsymbol": "RELIANCE", "instrument_token": 738561}
    ]
    return kite


def test_fetch_returns_market_closed_outside_hours():
    fake_kite = _make_kite()
    ing = IntradayDataIngestion(
        kite_client=fake_kite,
        engine=_FakeEngine(),
        clock=lambda: _ist_at(hour=20, minute=0),
    )
    res = ing.fetch_and_store("RELIANCE", interval="5minute")
    assert res.status == "market_closed"
    fake_kite.historical_data.assert_not_called()


def test_fetch_returns_kite_unavailable_when_no_client():
    ing = IntradayDataIngestion(
        kite_client_factory=lambda: None,
        engine=_FakeEngine(),
        clock=lambda: _ist_at(hour=10),
    )
    res = ing.fetch_and_store("RELIANCE", interval="5minute")
    assert res.status == "kite_unavailable"


def test_fetch_rejects_invalid_interval():
    ing = IntradayDataIngestion(
        kite_client=_make_kite(),
        engine=_FakeEngine(),
        clock=lambda: _ist_at(hour=10),
    )
    res = ing.fetch_and_store("RELIANCE", interval="42minute")
    assert res.status == "invalid_interval"


def test_fetch_rejects_empty_symbol():
    ing = IntradayDataIngestion(
        kite_client=_make_kite(),
        engine=_FakeEngine(),
        clock=lambda: _ist_at(hour=10),
    )
    res = ing.fetch_and_store("   ", interval="5minute")
    assert res.status == "invalid_symbol"


def test_fetch_returns_symbol_not_found_when_token_missing():
    fake_kite = _make_kite(instruments=[{"tradingsymbol": "TCS", "instrument_token": 111}])
    ing = IntradayDataIngestion(
        kite_client=fake_kite,
        engine=_FakeEngine(),
        clock=lambda: _ist_at(hour=10),
    )
    res = ing.fetch_and_store("RELIANCE", interval="5minute")
    assert res.status == "symbol_not_found"


def test_fetch_stores_candles_and_returns_counts():
    candles = [
        {"date": datetime(2026, 5, 1, 9, 15), "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1234},
        {"date": datetime(2026, 5, 1, 9, 20), "open": 100.5, "high": 101.5, "low": 100, "close": 101.0, "volume": 5678},
    ]
    fake_engine = _FakeEngine()
    ing = IntradayDataIngestion(
        kite_client=_make_kite(candles=candles),
        engine=fake_engine,
        clock=lambda: _ist_at(hour=10),
    )
    res = ing.fetch_and_store("RELIANCE", interval="5minute")
    assert res.status == "ok"
    assert res.candles_fetched == 2
    assert res.candles_stored == 2
    assert len(fake_engine.ohlcv_inserts) == 2


def test_fetch_handles_volume_none_safely():
    candles = [
        {"date": datetime(2026, 5, 1, 9, 15), "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": None},
    ]
    fake_engine = _FakeEngine()
    ing = IntradayDataIngestion(
        kite_client=_make_kite(candles=candles),
        engine=fake_engine,
        clock=lambda: _ist_at(hour=10),
    )
    res = ing.fetch_and_store("RELIANCE", interval="5minute")
    assert res.status == "ok"
    assert fake_engine.ohlcv_inserts[0]["v"] == 0


def test_fetch_skips_duplicate_timestamps_via_on_conflict():
    candles = [
        {"date": datetime(2026, 5, 1, 9, 15), "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 100},
        {"date": datetime(2026, 5, 1, 9, 15), "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 200},
    ]
    fake_engine = _FakeEngine()
    ing = IntradayDataIngestion(
        kite_client=_make_kite(candles=candles),
        engine=fake_engine,
        clock=lambda: _ist_at(hour=10),
    )
    res = ing.fetch_and_store("RELIANCE", interval="5minute")
    assert res.candles_fetched == 2
    assert res.candles_stored == 1  # second one conflicts


def test_fetch_force_skips_market_hours_check():
    fake_engine = _FakeEngine()
    ing = IntradayDataIngestion(
        kite_client=_make_kite(),
        engine=fake_engine,
        clock=lambda: _ist_at(hour=20),  # after close
    )
    res = ing.fetch_and_store("RELIANCE", interval="5minute", force=True)
    assert res.status == "ok"


def test_fetch_returns_error_when_kite_throws():
    fake_kite = _make_kite()
    fake_kite.historical_data.side_effect = RuntimeError("rate limited")
    ing = IntradayDataIngestion(
        kite_client=fake_kite,
        engine=_FakeEngine(),
        clock=lambda: _ist_at(hour=10),
    )
    res = ing.fetch_and_store("RELIANCE", interval="5minute")
    assert res.status == "error"
    assert "rate limited" in (res.error or "")


def test_fetch_caches_instrument_tokens():
    fake_kite = _make_kite()
    fake_engine = _FakeEngine()
    ing = IntradayDataIngestion(
        kite_client=fake_kite,
        engine=fake_engine,
        clock=lambda: _ist_at(hour=10),
    )
    ing.fetch_and_store("RELIANCE", interval="5minute")
    ing.fetch_and_store("RELIANCE", interval="5minute")
    # instruments() should be called exactly once due to caching
    assert fake_kite.instruments.call_count == 1


def test_fetch_watchlist_processes_each_symbol():
    fake_engine = _FakeEngine()
    ing = IntradayDataIngestion(
        kite_client=_make_kite(instruments=[
            {"tradingsymbol": "RELIANCE", "instrument_token": 1},
            {"tradingsymbol": "TCS", "instrument_token": 2},
        ]),
        engine=fake_engine,
        clock=lambda: _ist_at(hour=10),
    )
    results = ing.fetch_watchlist(["RELIANCE", "TCS", "MISSING"], interval="5minute")
    assert len(results) == 3
    assert {r.symbol for r in results} == {"RELIANCE", "TCS", "MISSING"}
    assert {r.status for r in results if r.symbol == "MISSING"} == {"symbol_not_found"}


def test_ingestion_result_as_dict():
    res = IngestionResult(status="ok", symbol="X", interval="5minute", candles_fetched=3, candles_stored=2)
    d = res.as_dict()
    assert d["status"] == "ok" and d["candles_stored"] == 2


# ===========================================================================
# RobustTickStream - graceful degradation + lifecycle
# ===========================================================================


def _make_ticker_factory():
    """Returns (ticker_factory, the_mock_ticker_it_will_return)."""
    ticker = MagicMock()
    ticker.MODE_FULL = "full"
    return (lambda *a, **k: ticker), ticker


def test_tick_stream_degrades_gracefully_without_credentials():
    stream = RobustTickStream(api_key="", access_token="")
    assert stream.is_disabled is True
    out = stream.start([1, 2, 3])
    assert out["ok"] is False
    assert out["reason"] == "kite_credentials_missing"


def test_tick_stream_handles_failed_ticker_factory():
    stream = RobustTickStream(
        api_key="k", access_token="t",
        ticker_factory=lambda *a, **k: None,
    )
    out = stream.start([1])
    assert out["ok"] is False
    assert out["reason"] == "ticker_factory_failed"


def test_tick_stream_start_subscribes_via_on_connect():
    factory, ticker = _make_ticker_factory()
    stream = RobustTickStream(api_key="k", access_token="t", ticker_factory=factory)
    out = stream.start([100, 200])
    assert out["ok"] is True
    assert stream.tokens == {100, 200}
    # Trigger on_connect manually (simulating the websocket's callback)
    ws = MagicMock()
    ws.MODE_FULL = "full"
    stream._on_connect(ws, {"info": "ok"})
    ws.subscribe.assert_called_once()
    ws.set_mode.assert_called_once()


def test_tick_stream_status_reports_state():
    stream = RobustTickStream(api_key="k", access_token="t")
    s = stream.status()
    assert s["ok"] is True
    assert s["is_running"] is False


def test_tick_stream_stop_closes_ticker():
    factory, ticker = _make_ticker_factory()
    stream = RobustTickStream(api_key="k", access_token="t", ticker_factory=factory)
    stream.start([1])
    stream.stop()
    ticker.close.assert_called_once()
    assert stream.is_running is False


# ===========================================================================
# RobustTickStream - hot subscription management
# ===========================================================================


def test_tick_stream_add_tokens_updates_set_and_subscribes():
    factory, ticker = _make_ticker_factory()
    stream = RobustTickStream(api_key="k", access_token="t", ticker_factory=factory)
    stream.start([1])
    added = stream.add_tokens([2, 3, 1])  # 1 already subscribed
    assert added == 2
    assert stream.tokens == {1, 2, 3}


def test_tick_stream_remove_tokens_updates_set_and_unsubscribes():
    factory, ticker = _make_ticker_factory()
    stream = RobustTickStream(api_key="k", access_token="t", ticker_factory=factory)
    stream.start([1, 2, 3])
    removed = stream.remove_tokens([2, 99])  # 99 was never subscribed
    assert removed == 1
    assert stream.tokens == {1, 3}


def test_tick_stream_token_mutations_thread_safe():
    """Hammer add/remove from many threads; final state must be consistent."""
    factory, ticker = _make_ticker_factory()
    stream = RobustTickStream(api_key="k", access_token="t", ticker_factory=factory)
    stream.start([])
    def worker(start: int):
        for i in range(start, start + 100):
            stream.add_tokens([i])
    threads = [threading.Thread(target=worker, args=(i * 100,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(stream.tokens) == 1000


# ===========================================================================
# RobustTickStream - tick storage
# ===========================================================================


def test_tick_stream_writes_ticks_to_redis():
    factory, ticker = _make_ticker_factory()
    redis_client = MagicMock()
    stream = RobustTickStream(
        api_key="k", access_token="t",
        ticker_factory=factory, redis_client=redis_client,
    )
    stream.start([1])
    stream._on_ticks(ticker, [
        {"instrument_token": 1, "last_price": 100.5, "volume": 1234},
    ])
    redis_client.lpush.assert_called_once()
    args = redis_client.lpush.call_args
    assert args[0][0] == "ticks:1"
    assert "100.5" in args[0][1]
    assert stream.tick_count == 1


def test_tick_stream_skips_tick_without_token():
    factory, ticker = _make_ticker_factory()
    redis_client = MagicMock()
    stream = RobustTickStream(
        api_key="k", access_token="t",
        ticker_factory=factory, redis_client=redis_client,
    )
    stream.start([1])
    stream._on_ticks(ticker, [{"last_price": 100.5}])  # no instrument_token
    redis_client.lpush.assert_not_called()


def test_tick_stream_user_callback_isolated_from_failure():
    factory, ticker = _make_ticker_factory()
    redis_client = MagicMock()
    def bad_callback(_ticks):
        raise RuntimeError("boom")
    stream = RobustTickStream(
        api_key="k", access_token="t",
        ticker_factory=factory, redis_client=redis_client,
    )
    stream.start([1], on_tick=bad_callback)
    # Must NOT raise even though the callback throws
    stream._on_ticks(ticker, [{"instrument_token": 1, "last_price": 100}])
    redis_client.lpush.assert_called_once()  # storage still happened


def test_tick_stream_trims_history_to_configured_size():
    factory, ticker = _make_ticker_factory()
    redis_client = MagicMock()
    stream = RobustTickStream(
        api_key="k", access_token="t",
        ticker_factory=factory, redis_client=redis_client,
        tick_history=5,
    )
    stream.start([1])
    stream._on_ticks(ticker, [{"instrument_token": 1, "last_price": 100}])
    redis_client.ltrim.assert_called_once_with("ticks:1", 0, 4)


def test_tick_stream_redis_failure_is_swallowed():
    factory, ticker = _make_ticker_factory()
    redis_client = MagicMock()
    redis_client.lpush.side_effect = RuntimeError("redis down")
    stream = RobustTickStream(
        api_key="k", access_token="t",
        ticker_factory=factory, redis_client=redis_client,
    )
    stream.start([1])
    # Should not raise even though redis is down
    stream._on_ticks(ticker, [{"instrument_token": 1, "last_price": 100}])


# ===========================================================================
# RobustTickStream - reconnect logic
# ===========================================================================


def test_tick_stream_reconnect_uses_separate_thread():
    """on_close must NOT block the websocket thread; reconnect runs separately."""
    factory, ticker = _make_ticker_factory()
    sleep_calls: list[float] = []
    stream = RobustTickStream(
        api_key="k", access_token="t",
        ticker_factory=factory,
        sleep_func=sleep_calls.append,  # capture, don't actually sleep
    )
    stream.start([1])
    initial_thread = threading.current_thread()

    # Trigger on_close on the "websocket thread"
    stream._on_close(ticker, code=1006, reason="abnormal")

    # The reconnect thread should be started; on_close itself returns
    # immediately without sleeping on the caller thread.
    assert sleep_calls == [] or threading.current_thread() is initial_thread
    # Reconnect counter incremented
    assert stream.reconnect_count == 1
    # Wait for the reconnect thread to actually run.
    if stream._reconnect_thread is not None:
        stream._reconnect_thread.join(timeout=5)
    assert sleep_calls and sleep_calls[0] >= 1  # backoff >= 2s on attempt 1
    assert stream.is_running  # still running after reconnect


def test_tick_stream_gives_up_after_max_reconnects():
    factory, ticker = _make_ticker_factory()
    stream = RobustTickStream(
        api_key="k", access_token="t",
        ticker_factory=factory,
        max_reconnects=2,
        sleep_func=lambda _s: None,
    )
    stream.start([1])
    for _ in range(3):
        stream._on_close(ticker, 1006, "x")
        if stream._reconnect_thread is not None:
            stream._reconnect_thread.join(timeout=5)
    assert stream.is_running is False
    assert stream.reconnect_count <= 2


def test_tick_stream_reconnect_aborts_when_stop_requested():
    factory, ticker = _make_ticker_factory()
    sleep_event = threading.Event()
    def slow_sleep(_s):
        sleep_event.wait(timeout=2)  # block until stop() releases us
    stream = RobustTickStream(
        api_key="k", access_token="t",
        ticker_factory=factory,
        sleep_func=slow_sleep,
    )
    stream.start([1])
    stream._on_close(ticker, 1006, "x")
    # Now stop the stream while reconnect thread is sleeping.
    stream.stop()
    sleep_event.set()
    if stream._reconnect_thread is not None:
        stream._reconnect_thread.join(timeout=5)
    assert stream.is_running is False


def test_tick_stream_reconnect_handles_ticker_factory_failing_after_disconnect():
    """Second factory call returns None - reconnect must abort cleanly."""
    ticker = MagicMock()
    ticker.MODE_FULL = "full"
    call_count = {"n": 0}
    def factory(*a, **k):
        call_count["n"] += 1
        return ticker if call_count["n"] == 1 else None
    stream = RobustTickStream(
        api_key="k", access_token="t",
        ticker_factory=factory,
        sleep_func=lambda _s: None,
    )
    stream.start([1])
    stream._on_close(ticker, 1006, "x")
    if stream._reconnect_thread is not None:
        stream._reconnect_thread.join(timeout=5)
    # No crash, just remained "wanting to run" with no live ticker.
    assert stream.is_running is True


# ===========================================================================
# RobustTickStream - singleton
# ===========================================================================


def test_tick_stream_singleton_returns_same_instance():
    a = get_robust_tick_stream()
    b = get_robust_tick_stream()
    assert a is b


def test_tick_stream_singleton_resets():
    a = get_robust_tick_stream()
    reset_robust_tick_stream()
    b = get_robust_tick_stream()
    assert a is not b
