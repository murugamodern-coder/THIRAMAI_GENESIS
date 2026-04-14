"""Part D: indicators, signals, portfolio math."""

from __future__ import annotations

import numpy as np
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import core.database as core_db
from core.db.base import Base
from core.db.models import EquityPortfolioPosition, EquityPortfolioTransaction, User
from services import portfolio_service as ps
from services.stock_indicator_service import bollinger_position, rsi_series
from services.stock_signal_service import generate_intraday_signal


@pytest.fixture
def sqlite_equity(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            User.__table__,
            EquityPortfolioPosition.__table__,
            EquityPortfolioTransaction.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    monkeypatch.setattr(core_db, "get_session_factory", lambda: factory)
    # ``portfolio_service`` binds ``get_session_factory`` at import time; patch the module copy.
    monkeypatch.setattr(ps, "get_session_factory", lambda: factory)
    with factory() as session:
        with session.begin():
            u = User(email="equity@test.local", password_hash="x", is_active=True)
            session.add(u)
            session.flush()
            uid = int(u.id)
    yield factory, uid
    engine.dispose()


def test_rsi_series_oversold_trend():
    """Steady decline → RSI should land in lower half."""
    x = np.array([100 - i * 0.5 for i in range(40)], dtype=float)
    r = rsi_series(x, 14)
    assert r is not None
    assert r < 50


def test_bollinger_inside_band():
    flat = np.array([100.0 + (i % 3) * 0.1 for i in range(30)], dtype=float)
    bb = bollinger_position(flat, 20, 2.0)
    assert bb["position"] == "inside"


def test_generate_intraday_signal_buy_on_rsi(monkeypatch: pytest.MonkeyPatch):
    def fake_ind(sym: str, **kwargs):
        return {
            "ok": True,
            "symbol": sym,
            "rsi": 25.0,
            "macd": 0.5,
            "macd_signal": 0.4,
            "ema9": 101.0,
            "ema21": 99.0,
            "macd_histogram": 0.05,
            "ema_signal": "bullish_cross",
            "trend": "bullish",
            "last_close": 100.0,
        }

    def fake_px(sym: str, **kwargs):
        return {"ok": True, "last": 100.0, "symbol": sym}

    monkeypatch.setattr("services.stock_signal_service.analyze_indicators", fake_ind)
    monkeypatch.setattr("services.stock_signal_service.get_live_price", fake_px)
    out = generate_intraday_signal("ZZTEST", user_id=None)
    assert out.get("ok") is True
    assert out.get("action") == "BUY"


def test_portfolio_avg_and_sell_realized(sqlite_equity, monkeypatch: pytest.MonkeyPatch):
    factory, uid = sqlite_equity

    def fake_px(symbol: str, **kwargs):
        return {"ok": True, "last": 120.0, "symbol": symbol}

    monkeypatch.setattr("services.stock_market_data_service.get_live_price", fake_px)

    a1 = ps.add_stock_sync(uid, "TESTCO", 10, 100)
    assert a1["ok"] is True
    a2 = ps.add_stock_sync(uid, "TESTCO", 10, 120)
    assert a2["ok"] is True
    # avg = (1000+1200)/20 = 110
    with factory() as session:
        row = session.execute(select(EquityPortfolioPosition).where(EquityPortfolioPosition.user_id == uid)).scalar_one()
        assert float(row.quantity) == 20
        assert float(row.avg_buy_price_inr) == 110.0

    s1 = ps.sell_stock_sync(uid, "TESTCO", 10, 130)
    assert s1["ok"] is True
    assert float(s1["realized_pnl_inr"]) == pytest.approx(200.0, rel=1e-4)

    summ = ps.get_portfolio_summary_sync(uid)
    assert summ["ok"] is True
    assert len(summ["positions"]) == 1
    pos = summ["positions"][0]
    assert float(pos["quantity"]) == 10
    # last 120 vs avg 110 on 10 qty -> +100 unrealized
    assert float(pos["pnl_inr"]) == pytest.approx(100.0, rel=1e-3)
