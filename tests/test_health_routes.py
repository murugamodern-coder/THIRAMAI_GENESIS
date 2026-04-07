"""Unified health endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from main import app


def test_health_live_ok() -> None:
    c = TestClient(app)
    r = c.get("/health/live")
    assert r.status_code == 200
    assert r.json().get("status") == "alive"


def test_health_index_discovery() -> None:
    c = TestClient(app)
    r = c.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body.get("live") == "/health/live"
    assert body.get("ready") == "/health/ready"


def test_health_ready_shape() -> None:
    c = TestClient(app)
    r = c.get("/health/ready")
    assert r.status_code in (200, 503)
    body = r.json()
    assert "checks" in body
    assert "schema_mode" in body["checks"]
    assert "ai" in body["checks"]


def test_dashboard_live_returns_html() -> None:
    c = TestClient(app)
    r = c.get("/dashboard/live")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    body = r.text
    assert "Executive Cockpit" in body or "THIRAMAI" in body
    assert "/health/live" in body


def test_dashboard_live_state_json() -> None:
    c = TestClient(app)
    r = c.get("/dashboard/live/state.json")
    assert r.status_code == 200
    j = r.json()
    assert j.get("schema") == "thiramai.dashboard_state.v1"
    assert "overall_green" in j
    assert "predictive_mode" in j


def test_dashboard_clear_thought_stream() -> None:
    c = TestClient(app)
    r = c.post("/dashboard/live/action/clear-thought-stream")
    assert r.status_code == 200
    assert r.json().get("ok") is True


def test_corporate_setup_identity_requires_auth_when_no_dashboard_token(monkeypatch) -> None:
    monkeypatch.setenv("THIRAMAI_DASHBOARD_ACTION_TOKEN", "")
    monkeypatch.setenv("THIRAMAI_AUTH_DISABLED", "0")
    c = TestClient(app)
    r = c.post("/dashboard/setup/identity", json={"company_name": "TestCo", "gst_number": ""})
    assert r.status_code == 401
