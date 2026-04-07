"""Phase 4: autonomous decision_trigger + dedupe + billing snapshot path."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import core.database as core_db
from core.db.base import Base
from core.db.models import AiDecision, Inventory, InventoryItem, Organization, StockMovement
from services import approval_service as ai_decision_store
from services import decision_trigger
from services import inventory_phase2_service as inv2


@pytest.fixture
def sqlite_auto(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Organization.__table__,
            Inventory.__table__,
            InventoryItem.__table__,
            StockMovement.__table__,
            AiDecision.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as s:
        with s.begin():
            s.add(Organization(id=1, name="T", plan="free"))
    monkeypatch.setattr(core_db, "get_session_factory", lambda: factory)
    monkeypatch.setattr(inv2, "get_session_factory", lambda: factory)
    monkeypatch.setattr(ai_decision_store, "get_session_factory", lambda: factory)
    monkeypatch.setattr(decision_trigger, "get_session_factory", lambda: factory)
    monkeypatch.setattr(inv2.system_audit, "record_system_audit", lambda **kwargs: None)
    monkeypatch.setattr(decision_trigger.system_audit, "record_system_audit", lambda **kwargs: None)
    monkeypatch.setattr(decision_trigger.action_executor, "execute_decision", lambda **kwargs: {"ok": True, "result": {}})
    monkeypatch.setattr(
        decision_trigger,
        "run_decision_engine_sync",
        lambda *args, **kwargs: {"ok": False, "decision": None, "error": "no groq in test"},
    )
    yield factory, 1
    engine.dispose()


def test_low_stock_automation_creates_decision(sqlite_auto, monkeypatch: pytest.MonkeyPatch):
    factory, oid = sqlite_auto
    monkeypatch.setenv("THIRAMAI_AUTOMATION_AUTO_APPROVE_LOW_STOCK", "1")

    inv2.create_inventory_item_sync(
        organization_id=oid,
        sku_name="AUTO-SKU",
        location="W",
        quantity=1,
        reorder_point=10,
        user_id=None,
    )
    out = decision_trigger.process_low_stock_automation(oid)
    assert out.get("ok") is True
    assert int(out.get("triggered") or 0) >= 1

    with factory() as session:
        rows = list(session.scalars(select(AiDecision).where(AiDecision.organization_id == oid)).all())
        assert len(rows) == 1
        assert rows[0].action == "reorder_stock"
        assert rows[0].correlation_id.startswith("automation:low_stock:")


def test_low_stock_dedupe_same_day(sqlite_auto, monkeypatch: pytest.MonkeyPatch):
    factory, oid = sqlite_auto
    monkeypatch.setenv("THIRAMAI_AUTOMATION_AUTO_APPROVE_LOW_STOCK", "1")

    inv2.create_inventory_item_sync(
        organization_id=oid,
        sku_name="DEDUPE",
        location="",
        quantity=1,
        reorder_point=5,
        user_id=None,
    )
    a1 = decision_trigger.process_low_stock_automation(oid)
    assert int(a1.get("triggered") or 0) == 1
    a2 = decision_trigger.process_low_stock_automation(oid)
    assert int(a2.get("triggered") or 0) == 0
    assert int(a2.get("skipped") or 0) >= 1

    with factory() as session:
        n = len(list(session.scalars(select(AiDecision).where(AiDecision.organization_id == oid)).all()))
        assert n == 1


def test_overdue_invoice_fallback(sqlite_auto, monkeypatch: pytest.MonkeyPatch):
    factory, oid = sqlite_auto
    monkeypatch.setenv("THIRAMAI_AUTOMATION_AUTO_APPROVE_REMINDERS", "1")

    def fake_snapshot(o: int) -> dict:
        return {
            "ok": True,
            "organization_id": o,
            "financial_summary": {"overdue_invoice_ids": [42]},
            "production_status": {},
        }

    monkeypatch.setattr(decision_trigger, "build_business_context_snapshot", fake_snapshot)
    out = decision_trigger.process_overdue_invoice_automation(oid)
    assert out.get("triggered") == 1

    with factory() as session:
        rows = list(session.scalars(select(AiDecision).where(AiDecision.organization_id == oid)).all())
        assert len(rows) == 1
        assert rows[0].action == "send_payment_reminder"
