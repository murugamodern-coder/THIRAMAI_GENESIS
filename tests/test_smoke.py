"""Minimal CI smoke tests (import app + health route)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from main import app


def test_app_import() -> None:
    assert app.title


def test_health_root() -> None:
    client = TestClient(app)
    r = client.get("/", headers={"Accept": "application/json"})
    assert r.status_code == 200
    assert "status" in r.json()


def test_root_spa_html_without_json_accept() -> None:
    """Browser-style GET / should receive HTML when static/index.html exists."""
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    ct = (r.headers.get("content-type") or "").lower()
    if "application/json" in ct:
        assert "status" in r.json()
        return
    assert "text/html" in ct
    assert b"THIRAMAI" in r.content or b"thiramai" in r.content.lower()
