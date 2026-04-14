"""Upgrade 4 — stock realtime monitor, alerts, risk, WebSocket smoke."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from api.dependencies import CurrentUser
from main import app
from services.stock_realtime_monitor import StockRealtimeMonitor, stock_monitor


def test_evaluate_alerts_above():
    mon = StockRealtimeMonitor()
    rows = [{"id": 1, "symbol": "AAA", "condition": "above", "price_threshold": "100", "action": "notify"}]
    prices = {"AAA": {"ok": True, "last": 105.0}}
    fired = mon.evaluate_alerts(1, prices, rows)
    assert len(fired) == 1
    assert fired[0]["type"] == "price_alert"


def test_evaluate_alerts_cooldown():
    mon = StockRealtimeMonitor()
    rows = [{"id": 2, "symbol": "BBB", "condition": "below", "price_threshold": "50", "action": "notify"}]
    prices = {"BBB": {"ok": True, "last": 40.0}}
    assert len(mon.evaluate_alerts(1, prices, rows)) == 1
    assert len(mon.evaluate_alerts(1, prices, rows)) == 0


def test_detect_ema_cross_bull():
    mon = StockRealtimeMonitor()
    ind0 = {"ok": True, "ema9": 10.0, "ema21": 11.0, "macd_histogram": -0.1}
    mon.detect_signal_events(1, "X", ind0)
    ind1 = {"ok": True, "ema9": 12.0, "ema21": 11.0, "macd_histogram": 0.2}
    ev = mon.detect_signal_events(1, "X", ind1)
    kinds = [e.get("kind") for e in ev]
    assert "ema_bullish_cross" in kinds


@patch("services.jarvis_proactive_service.upsert_equity_stop_trading_alert_sync")
@patch("services.stock_realtime_monitor.daily_equity_pnl_inr_sync")
def test_check_risk_limits_triggers(mock_pnl, mock_upsert):
    mock_pnl.return_value = Decimal("-2500")
    mon = StockRealtimeMonitor()
    mon._user_org[7] = 1
    out = mon.check_risk_limits(7)
    assert out is not None
    assert out["type"] == "risk_stop"
    mock_upsert.assert_called_once()


@patch("services.stock_realtime_monitor.daily_equity_pnl_inr_sync", return_value=Decimal("0"))
@patch("services.stock_realtime_monitor.get_portfolio_summary_sync")
@patch("services.stock_realtime_monitor.analyze_indicators")
@patch("services.stock_realtime_monitor.get_live_price")
@patch("services.stock_realtime_monitor.list_stock_alerts_sync")
@patch("services.stock_realtime_monitor.list_watchlist_symbols_sync")
def test_compose_tick_sync(mock_wl, mock_alerts, mock_price, mock_ind, mock_port, _mock_pnl):
    mock_wl.return_value = ["TCS"]
    mock_alerts.return_value = []
    mock_price.return_value = {"ok": True, "last": 100.0, "cached": False}
    mock_ind.return_value = {"ok": True, "ema9": 1, "ema21": 2, "macd_histogram": 0.1}
    mock_port.return_value = {"ok": True, "positions": [], "daily_realized_pnl_inr": "0", "risk_blocked": False}
    mon = StockRealtimeMonitor()
    payload = mon.compose_tick_sync(1)
    assert payload["type"] == "stock_tick"
    assert "TCS" in payload["prices"]


@patch("api.routes.stock_ws.stock_monitor.ensure_poll_task", new_callable=AsyncMock)
@patch("api.routes.stock_ws.try_resolve_current_user_from_access_token")
def test_ws_stocks_synthetic_tick(mock_resolve, mock_ensure):
    mock_resolve.return_value = CurrentUser(
        id=1,
        email="t@example.com",
        organization_id=1,
        role_name="owner",
        role_level=1,
        is_active=True,
    )
    with TestClient(app) as client:
        with client.websocket_connect("/ws/stocks/1") as ws:
            ws.send_json({"token": "fake-jwt"})
            ready = ws.receive_json()
            assert ready.get("type") == "stock_ws_ready"
            stock_monitor.push_synthetic_tick(
                1,
                {"type": "stock_tick", "prices": {"RELIANCE": {"ok": True, "last": 2500}}, "watchlist": ["RELIANCE"]},
            )
            tick = ws.receive_json()
            assert tick.get("type") == "stock_tick"
            assert tick.get("prices", {}).get("RELIANCE", {}).get("last") == 2500
