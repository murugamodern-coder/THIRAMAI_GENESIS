from __future__ import annotations

from fastapi.testclient import TestClient

from app import app
from core.security_middleware import _cors_origins


def test_security_headers_present() -> None:
    client = TestClient(app)
    r = client.get("/health/live")
    assert r.status_code == 200

    assert "content-security-policy" in r.headers
    assert "permissions-policy" in r.headers
    assert "cross-origin-opener-policy" in r.headers
    assert "cross-origin-embedder-policy" in r.headers
    assert "x-content-type-options" in r.headers
    assert "x-frame-options" in r.headers
    assert "referrer-policy" in r.headers


def test_csp_not_too_permissive() -> None:
    client = TestClient(app)
    r = client.get("/health/live")
    csp = r.headers.get("content-security-policy", "")

    assert csp
    assert "default-src 'none'" in csp or "default-src 'self'" in csp
    assert "*" not in csp
    assert "'unsafe-eval'" not in csp


def test_cors_not_wildcard_in_production(monkeypatch) -> None:
    monkeypatch.setenv("THIRAMAI_CORS_ORIGINS", "https://app.thiramai.example,https://thiramai.example")
    origins = _cors_origins()

    assert "*" not in origins
    assert "https://app.thiramai.example" in origins
