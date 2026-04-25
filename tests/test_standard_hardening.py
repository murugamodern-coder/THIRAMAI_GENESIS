"""International hardening: cache keys/TTL, AI citations, security headers behavior."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from cache.keys import build_stable_key, key_today_brief
from cache.ttl import today_brief_ttl_seconds
from core.ai_output_contract import apply_ai_safety_envelope, extract_url_citations
from core.security_middleware import SecurityHeadersMiddleware


def test_cache_key_idempotent():
    a = key_today_brief(1, 2, "2026-04-01")
    b = key_today_brief(1, 2, "2026-04-01")
    assert a == b
    assert a.startswith("thiramai:appcache:")
    assert build_stable_key("x", "y") != build_stable_key("x", "z")


def test_today_brief_ttl_non_negative():
    assert today_brief_ttl_seconds() >= 0


def test_extract_url_citations():
    src = extract_url_citations("Read https://example.com/path?q=1 and also http://a.org/x).")
    assert any(s.startswith("https://example.com") for s in src)
    assert any("a.org" in s for s in src)


def test_ai_safety_envelope_low_confidence(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("THIRAMAI_AI_MIN_CONFIDENCE", "0.95")
    payload = {"narrative": "maybe unknown", "response": "maybe unknown"}
    out = apply_ai_safety_envelope(payload, narrative=payload["narrative"], sources=[])
    assert "confidence_score" in out
    assert out.get("ai_safety", {}).get("low_confidence_suppressed") is True


def test_security_headers_strip_server_in_production(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("THIRAMAI_ENV", "production")

    async def route(_):
        r = JSONResponse({})
        r.headers["Server"] = "uvicorn"
        r.headers["X-Powered-By"] = "Express"
        return r

    app = Starlette(routes=[Route("/probe", route)])
    app.add_middleware(SecurityHeadersMiddleware)
    with TestClient(app) as client:
        h = client.get("/probe").headers
    assert "server" not in h
    assert "x-powered-by" not in h


def test_security_headers_allow_inline_styles_for_spa():
    async def route(_):
        return JSONResponse({})

    app = Starlette(routes=[Route("/", route)])
    app.add_middleware(SecurityHeadersMiddleware)
    with TestClient(app) as client:
        csp = client.get("/").headers.get("content-security-policy", "")
    assert "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'" in csp
