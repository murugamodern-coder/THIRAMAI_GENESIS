"""usage_logs table + analytics summary (Phase 8)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from core.database import get_session_factory, reset_engine_cache
from core.db.base import Base
from core.db.models import AiDecision, Bill, Inventory, Organization, UsageLog
from services.usage_log_service import build_analytics_summary_sync, log_usage_sync


@pytest.fixture
def sqlite_usage_engine(monkeypatch: pytest.MonkeyPatch):
    sqlite_url = "sqlite+pysqlite:///:memory:"
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    # Secrets layer can override plain env; pin the URL the DB module uses.
    monkeypatch.setattr("core.database.get_database_url", lambda: sqlite_url)
    reset_engine_cache()
    from core.database import get_engine

    eng = get_engine()
    assert eng is not None
    Base.metadata.create_all(
        bind=eng,
        tables=[
            Organization.__table__,
            UsageLog.__table__,
            AiDecision.__table__,
            Bill.__table__,
            Inventory.__table__,
        ],
    )
    factory = get_session_factory()
    assert factory is not None
    with factory() as session:
        with session.begin():
            session.add(Organization(id=1, name="Test Org", plan="free"))
    yield eng
    reset_engine_cache()
    monkeypatch.delenv("DATABASE_URL", raising=False)


def test_build_analytics_summary_no_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """No DB URL must short-circuit before opening a session.

    Do not rely only on ``delenv``: another test may have used an in-memory SQLite URL;
    after engine dispose the DB is empty but the URL can still resolve until cleared,
    which raises ``no such table`` instead of the intended ``ok: False``.
    """
    monkeypatch.setattr("core.database.get_database_url", lambda: None)
    reset_engine_cache()
    out = build_analytics_summary_sync(1)
    assert out.get("ok") is False


def test_log_and_summary_sqlite(sqlite_usage_engine) -> None:
    log_usage_sync(organization_id=1, user_id=None, action="login", metadata={"test": True})
    out = build_analytics_summary_sync(1, days=30)
    assert out.get("ok") is True
    assert out.get("organization_id") == 1
    assert out.get("usage_events_total", 0) >= 1
    assert "login" in (out.get("usage_events_by_action") or {})
