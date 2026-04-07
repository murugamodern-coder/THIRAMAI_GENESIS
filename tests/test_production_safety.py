"""Production configuration guards."""

from __future__ import annotations

import pytest

from core.production_safety import assert_safe_production_config


def test_production_forbids_auth_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("THIRAMAI_AUTH_DISABLED", "1")
    with pytest.raises(RuntimeError, match="THIRAMAI_AUTH_DISABLED"):
        assert_safe_production_config()


def test_production_forbids_auth_disabled_truthy_strings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("THIRAMAI_AUTH_DISABLED", "true")
    with pytest.raises(RuntimeError, match="THIRAMAI_AUTH_DISABLED"):
        assert_safe_production_config()


def test_thiramai_env_production_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setenv("THIRAMAI_ENV", "production")
    monkeypatch.setenv("THIRAMAI_AUTH_DISABLED", "1")
    with pytest.raises(RuntimeError, match="THIRAMAI_AUTH_DISABLED"):
        assert_safe_production_config()


def test_non_production_allows_auth_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("THIRAMAI_AUTH_DISABLED", "1")
    assert_safe_production_config()


def test_production_requires_safe_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("THIRAMAI_AUTH_DISABLED", "0")
    monkeypatch.setenv("THIRAMAI_CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("THIRAMAI_SAFE_ERRORS", "0")
    with pytest.raises(RuntimeError, match="THIRAMAI_SAFE_ERRORS"):
        assert_safe_production_config()
