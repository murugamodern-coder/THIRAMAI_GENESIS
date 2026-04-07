"""DB-backed idempotency (SQLite in CI)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.db.base import Base
from core.db.models import IdempotencyKey
from workers import idempotency as idem


@pytest.fixture
def sqlite_factory(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"autocommit": False})
    Base.metadata.create_all(bind=engine, tables=[IdempotencyKey.__table__])
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    monkeypatch.setattr(idem, "get_session_factory", lambda: SessionLocal)
    yield SessionLocal


def test_claim_then_duplicate(sqlite_factory):
    assert idem.try_claim_idempotency_slot("k1", "issue_invoice") == "run"
    idem.mark_idempotency_completed("k1", action_type="issue_invoice", meta={"risk_tier": "high"})
    assert idem.try_claim_idempotency_slot("k1", "issue_invoice") == "duplicate"


def test_release_allows_retry(sqlite_factory):
    assert idem.try_claim_idempotency_slot("k2", "issue_invoice") == "run"
    idem.release_idempotency_claim("k2")
    assert idem.try_claim_idempotency_slot("k2", "issue_invoice") == "run"
