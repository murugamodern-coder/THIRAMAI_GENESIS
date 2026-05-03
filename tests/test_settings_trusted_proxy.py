"""ThiramaiSettings trusted proxy env parsing (empty, JSON, comma-separated)."""

from __future__ import annotations

import pytest

from core.settings import ThiramaiSettings, _parse_thiramai_trusted_proxy_ips


def test_parse_empty_and_whitespace() -> None:
    assert _parse_thiramai_trusted_proxy_ips("") == []
    assert _parse_thiramai_trusted_proxy_ips("   ") == []


def test_parse_json_array() -> None:
    assert _parse_thiramai_trusted_proxy_ips("[]") == []
    assert _parse_thiramai_trusted_proxy_ips('["127.0.0.1", "10.0.0.1"]') == ["127.0.0.1", "10.0.0.1"]


def test_parse_comma_cidrs() -> None:
    assert _parse_thiramai_trusted_proxy_ips("10.0.0.0/8,172.16.0.0/12") == [
        "10.0.0.0/8",
        "172.16.0.0/12",
    ]


def test_parse_invalid_json_raises() -> None:
    with pytest.raises(ValueError, match="valid JSON array"):
        _parse_thiramai_trusted_proxy_ips("[}")


def test_settings_trusted_proxy_empty_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THIRAMAI_TRUSTED_PROXY_IPS", "")
    s = ThiramaiSettings()
    assert s.trusted_proxy_ips == []


def test_settings_trusted_proxy_json_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THIRAMAI_TRUSTED_PROXY_IPS", '["203.0.113.1"]')
    s = ThiramaiSettings()
    assert s.trusted_proxy_ips == ["203.0.113.1"]


def test_settings_trusted_proxy_comma_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THIRAMAI_TRUSTED_PROXY_IPS", "10.0.0.0/8,192.168.0.0/16")
    s = ThiramaiSettings()
    assert s.trusted_proxy_ips == ["10.0.0.0/8", "192.168.0.0/16"]


def test_settings_alias_trusted_proxy_ips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THIRAMAI_TRUSTED_PROXY_IPS", raising=False)
    monkeypatch.setenv("TRUSTED_PROXY_IPS", '["198.51.100.2"]')
    s = ThiramaiSettings()
    assert s.trusted_proxy_ips == ["198.51.100.2"]
