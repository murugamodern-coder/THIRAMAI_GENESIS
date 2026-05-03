"""Monitoring API routes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from main import app


def test_ai_quality_requires_auth_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("THIRAMAI_AUTH_DISABLED", "0")
    c = TestClient(app)
    r = c.get("/monitoring/ai-quality")
    assert r.status_code == 401


def test_ai_quality_ok_when_auth_disabled(monkeypatch) -> None:
    monkeypatch.setenv("THIRAMAI_AUTH_DISABLED", "1")
    from services.ai_quality_tracker import reset_quality_tracker_for_tests

    reset_quality_tracker_for_tests()
    c = TestClient(app)
    r = c.get("/monitoring/ai-quality")
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") in ("no_data", "ok")
