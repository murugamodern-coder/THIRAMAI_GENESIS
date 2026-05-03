"""Tests for core.secrets_manager and settings integration."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import pytest

from core.secrets_manager import (
    AWSSecretsManagerBackend,
    EnvironmentBackend,
    SecretsManager,
    get_secret,
    get_secrets_manager,
    reset_secrets_manager,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    reset_secrets_manager()
    yield
    reset_secrets_manager()


def test_environment_backend_get() -> None:
    backend = EnvironmentBackend()
    with patch.dict("os.environ", {"TEST_SECRET": "test_value"}, clear=False):
        assert backend.get_secret("TEST_SECRET") == "test_value"


def test_environment_backend_missing() -> None:
    backend = EnvironmentBackend()
    with patch.dict("os.environ", {}, clear=False):
        assert backend.get_secret("NONEXISTENT_SECRET_XYZ") is None


def test_secrets_manager_cache_ttl() -> None:
    backend = Mock()
    backend.get_secret = Mock(return_value="cached_value")
    mgr = SecretsManager(backend=backend, cache_ttl_seconds=60.0)

    assert mgr.get("K", use_cache=True) == "cached_value"
    assert mgr.get("K", use_cache=True) == "cached_value"
    assert backend.get_secret.call_count == 1


def test_secrets_manager_cache_bypass() -> None:
    backend = Mock()
    backend.get_secret = Mock(return_value="v")
    mgr = SecretsManager(backend=backend, cache_ttl_seconds=60.0)

    mgr.get("K", use_cache=False)
    mgr.get("K", use_cache=False)
    assert backend.get_secret.call_count == 2


def test_secrets_manager_set_invalidates_cache() -> None:
    backend = Mock()
    backend.get_secret = Mock(side_effect=["old", "new"])
    backend.set_secret = Mock(return_value=True)
    mgr = SecretsManager(backend=backend, cache_ttl_seconds=300.0)

    assert mgr.get("K") == "old"
    assert mgr.set("K", "x") is True
    assert mgr.get("K") == "new"
    assert backend.get_secret.call_count == 2


def test_get_secret_singleton() -> None:
    with patch.dict("os.environ", {"TEST_SECRET": "convenient"}, clear=False):
        assert get_secret("TEST_SECRET") == "convenient"


def test_get_secrets_manager_returns_same_instance() -> None:
    a = get_secrets_manager()
    b = get_secrets_manager()
    assert a is b


def test_aws_get_secret_json_value_key() -> None:
    client = MagicMock()
    client.get_secret_value.return_value = {"SecretString": '{"value": "x"}'}
    backend = AWSSecretsManagerBackend(region="us-east-1")
    backend._client = client  # type: ignore[attr-defined]

    assert backend.get_secret("mysecret") == "x"
    client.get_secret_value.assert_called_once_with(SecretId="mysecret")


def test_aws_get_secret_not_found() -> None:
    from botocore.exceptions import ClientError

    client = MagicMock()
    client.get_secret_value.side_effect = ClientError(
        {"Error": {"Code": "ResourceNotFoundException", "Message": "nope"}}, "GetSecretValue"
    )
    backend = AWSSecretsManagerBackend(region="us-east-1")
    backend._client = client  # type: ignore[attr-defined]

    assert backend.get_secret("missing") is None


def test_aws_set_put_then_create() -> None:
    from botocore.exceptions import ClientError

    client = MagicMock()
    client.put_secret_value.side_effect = ClientError(
        {"Error": {"Code": "ResourceNotFoundException", "Message": "nope"}}, "PutSecretValue"
    )
    backend = AWSSecretsManagerBackend(region="us-east-1")
    backend._client = client  # type: ignore[attr-defined]

    assert backend.set_secret("n", "v") is True
    client.create_secret.assert_called_once()


def test_rotate_clears_internal_cache() -> None:
    backend = Mock()
    backend.get_secret = Mock(side_effect=["first", "second"])
    backend.set_secret = Mock(return_value=True)
    mgr = SecretsManager(backend=backend, cache_ttl_seconds=300.0)

    mgr.get("K")
    assert mgr.rotate("K", "new", grace_period_seconds=0) is True
    assert mgr.get("K") == "second"


def test_cache_expires_by_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = Mock()
    backend.get_secret = Mock(return_value="x")
    mgr = SecretsManager(backend=backend, cache_ttl_seconds=0.01)
    _seq = iter([0.0, 1.0])
    monkeypatch.setattr("core.secrets_manager.time.monotonic", lambda: next(_seq))

    mgr.get("K")
    mgr.get("K")
    assert backend.get_secret.call_count == 2


def test_thiramai_settings_get_secret_or_env() -> None:
    from core.settings import ThiramaiSettings, reset_settings_cache

    reset_settings_cache()
    with patch.dict("os.environ", {"ZZZ_ABC": "from-env"}, clear=False):
        s = ThiramaiSettings()
        assert s.get_secret_or_env("ZZZ_ABC") == "from-env"
