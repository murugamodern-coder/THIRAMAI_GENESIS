"""Rate-limit hardening tests for proxy/IP spoofing."""

from __future__ import annotations

import logging

import pytest
from starlette.requests import Request

import core.rate_limit_middleware as rlm


def _request(remote_ip: str, xff: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode("utf-8")))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/auth/login",
        "headers": headers,
        "client": (remote_ip, 12345),
        "scheme": "http",
        "server": ("testserver", 80),
        "query_string": b"",
    }
    return Request(scope)


def test_spoofed_ip_rejected_when_proxy_not_trusted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THIRAMAI_RL_TRUST_X_FORWARDED_FOR", "1")
    monkeypatch.setenv("THIRAMAI_TRUSTED_PROXY_IPS", "10.0.0.0/8,172.16.0.0/12")
    rlm._WARNED_NO_PROXY_ALLOWLIST = False

    req = _request("203.0.113.10", xff="1.2.3.4")
    assert rlm._client_key(req) == "203.0.113.10"


def test_real_ip_used_when_no_trusted_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THIRAMAI_RL_TRUST_X_FORWARDED_FOR", "1")
    monkeypatch.delenv("THIRAMAI_TRUSTED_PROXY_IPS", raising=False)
    rlm._WARNED_NO_PROXY_ALLOWLIST = False

    req = _request("198.51.100.7", xff="9.9.9.9")
    assert rlm._client_key(req) == "198.51.100.7"


def test_rate_limit_applies_per_real_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THIRAMAI_RL_TRUST_X_FORWARDED_FOR", "1")
    monkeypatch.setenv("THIRAMAI_TRUSTED_PROXY_IPS", "10.0.0.0/8")
    rlm._HITS.clear()
    rlm._WARNED_NO_PROXY_ALLOWLIST = False

    req1 = _request("198.51.100.21", xff="1.1.1.1")
    req2 = _request("198.51.100.21", xff="2.2.2.2")
    key1 = (rlm._client_key(req1), "auth")
    key2 = (rlm._client_key(req2), "auth")
    assert key1 == key2 == ("198.51.100.21", "auth")

    assert rlm._prune_and_count(key1, now=100.0, window=60.0, limit=2) is True
    assert rlm._prune_and_count(key2, now=101.0, window=60.0, limit=2) is True
    assert rlm._prune_and_count(key2, now=102.0, window=60.0, limit=2) is False


def test_warning_logged_when_trust_enabled_no_allowlist(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("THIRAMAI_RL_TRUST_X_FORWARDED_FOR", "1")
    monkeypatch.delenv("THIRAMAI_TRUSTED_PROXY_IPS", raising=False)
    rlm._WARNED_NO_PROXY_ALLOWLIST = False

    caplog.set_level(logging.WARNING, logger=rlm.__name__)
    _ = rlm._client_key(_request("198.51.100.55", xff="8.8.8.8"))

    assert any("rate_limit.security_warning" in rec.getMessage() for rec in caplog.records)
    assert any("no proxy allowlist" in rec.getMessage().lower() for rec in caplog.records)
