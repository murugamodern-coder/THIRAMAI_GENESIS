"""Tests for SQLAlchemy connection pool configuration and observability hooks."""

from __future__ import annotations

import pytest

from api.routes.health import check_database_pool
from core.database import get_engine, reset_engine_cache
from core.settings import ThiramaiSettings, get_settings
from services.observability.business_metrics import update_pool_metrics


@pytest.fixture(autouse=True)
def _reset_engine():
    reset_engine_cache()
    yield
    reset_engine_cache()


def test_engine_uses_pool_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://user:pass@localhost:5432/db")
    monkeypatch.setenv("POOL_SIZE", "7")
    monkeypatch.setenv("MAX_OVERFLOW", "11")
    monkeypatch.setenv("POOL_TIMEOUT", "25")
    monkeypatch.setenv("POOL_RECYCLE", "1800")
    reset_engine_cache()
    s = ThiramaiSettings()
    assert s.POOL_SIZE == 7
    assert s.MAX_OVERFLOW == 11
    engine = get_engine()
    assert engine is not None
    assert engine.pool.size() == 7


def test_sqlite_engine_skips_large_queue_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    reset_engine_cache()
    engine = get_engine()
    assert engine is not None


def test_pool_pre_ping_enabled() -> None:
    assert get_settings().POOL_PRE_PING is True


def test_pool_metrics_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    reset_engine_cache()
    get_engine()
    update_pool_metrics()


def test_pool_health_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    reset_engine_cache()
    get_engine()
    result = check_database_pool()
    assert "status" in result
    assert result["status"] in ("healthy", "degraded", "unhealthy", "unknown")
    assert "pool_size" in result or result.get("detail")


def test_pool_sizing_for_load() -> None:
    s = get_settings()
    assert s.POOL_SIZE + s.MAX_OVERFLOW >= 50


def test_connection_timeout_reasonable() -> None:
    s = get_settings()
    assert 10 <= s.POOL_TIMEOUT <= 300
