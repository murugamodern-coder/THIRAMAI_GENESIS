"""WebSocket command center: /ws/dashboard push channel."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from api.dependencies import CurrentUser
from main import app


@patch("api.routes.dashboard_ws.build_command_center_sap_payload_sync")
@patch("api.routes.dashboard_ws.try_resolve_current_user_from_access_token")
def test_ws_dashboard_sends_dashboard_tick(mock_resolve, mock_build):
    mock_resolve.return_value = CurrentUser(
        id=1,
        email="t@example.com",
        organization_id=1,
        role_name="owner",
        role_level=1,
        is_active=True,
    )
    mock_build.return_value = {
        "schema": "thiramai.command_center.sap.v1",
        "life_dashboard": {"life_score": {}},
        "business_summary": {"ok": True},
        "alerts": [],
        "next_best_move": "Ship backlog",
        "as_of_utc": "2026-04-03T12:00:00+00:00",
    }

    with TestClient(app) as client:
        with client.websocket_connect("/ws/dashboard") as ws:
            ws.send_json({"token": "fake-jwt"})
            msg = ws.receive_json()
            assert msg["type"] == "dashboard_tick"
            assert msg["channel"] == "ws/dashboard"
            assert msg["next_best_move"] == "Ship backlog"
