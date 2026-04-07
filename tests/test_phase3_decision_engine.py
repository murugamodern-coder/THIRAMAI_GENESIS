"""Phase 3: business context snapshot, decision schema, RBAC, executor, ai_decisions persistence."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import core.database as core_db
from core.db.base import Base
from core.db.models import AiDecision, Organization
from core.decision_schema import AIDecision, decision_is_safe, parse_and_validate_decision
from core.decision_rbac import can_execute_decision
from services import action_executor
from services import approval_service as ai_decision_store
from services import audit_log as system_audit
from services import context_engine


@pytest.fixture
def sqlite_ai(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[Organization.__table__, AiDecision.__table__],
    )
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as s:
        with s.begin():
            s.add(Organization(id=1, name="T", plan="free"))
    monkeypatch.setattr(core_db, "get_session_factory", lambda: factory)
    yield factory, 1
    engine.dispose()


def test_build_business_context_snapshot_shape(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(context_engine, "get_session_factory", lambda: None)
    snap = context_engine.build_business_context_snapshot(1)
    assert snap["ok"] is True
    assert "inventory_alerts" in snap
    assert "financial_summary" in snap
    assert "production_status" in snap


def test_parse_and_validate_decision_noop():
    d, err = parse_and_validate_decision(
        {
            "action": "noop",
            "entity": "none",
            "data": {},
            "priority": "low",
            "requires_approval": False,
            "rationale": "test",
        }
    )
    assert err is None
    assert d is not None
    assert d.action == "noop"


def test_normalize_alias_order_stock():
    d, err = parse_and_validate_decision(
        {"action": "order_stock", "entity": "x", "data": {}, "priority": "medium", "requires_approval": True}
    )
    assert err is None
    assert d is not None
    assert d.action == "reorder_stock"


def test_decision_safety_reorder_missing_sku():
    d = AIDecision(
        action="reorder_stock",
        entity="inv",
        data={"quantity": 10},
        priority="high",
        requires_approval=True,
    )
    ok, msg = decision_is_safe(d)
    assert ok is False
    assert msg is not None


def test_rbac_customer_blocked_stock():
    d = AIDecision(
        action="reorder_stock",
        entity="inv",
        data={"sku_name": "X", "quantity": 1},
        priority="high",
        requires_approval=False,
    )
    ok, msg = can_execute_decision(role_name="customer", decision=d)
    assert ok is False


def test_execute_noop():
    d = AIDecision(action="noop", entity="x", data={}, priority="low", requires_approval=False)
    out = action_executor.execute_decision(organization_id=1, decision=d, user_id=None)
    assert out["ok"] is True


def test_insert_and_list_pending(sqlite_ai, monkeypatch: pytest.MonkeyPatch):
    factory, oid = sqlite_ai
    monkeypatch.setattr(ai_decision_store, "get_session_factory", lambda: factory)

    d = AIDecision(
        action="noop",
        entity="test",
        data={},
        priority="low",
        requires_approval=True,
    )
    ins = ai_decision_store.insert_ai_decision(
        organization_id=oid,
        user_id=None,
        decision=d,
        status="pending",
    )
    assert ins["ok"] is True
    lst = ai_decision_store.list_pending_ai_decisions(organization_id=oid)
    assert lst["ok"] is True
    assert len(lst["items"]) == 1


def test_resolve_rejected_no_execution(sqlite_ai, monkeypatch: pytest.MonkeyPatch):
    factory, oid = sqlite_ai
    monkeypatch.setattr(ai_decision_store, "get_session_factory", lambda: factory)
    monkeypatch.setattr(system_audit, "record_system_audit", lambda **kwargs: None)

    d = AIDecision(
        action="noop",
        entity="t",
        data={},
        priority="low",
        requires_approval=True,
    )
    ins = ai_decision_store.insert_ai_decision(organization_id=oid, user_id=None, decision=d, status="pending")
    assert ins["ok"] is True
    did = int(ins["id"])

    called = []

    def _no_exec(**kwargs):
        called.append(True)
        return {"ok": True, "result": {}}

    monkeypatch.setattr(ai_decision_store.action_executor, "execute_decision", _no_exec)

    out = ai_decision_store.resolve_ai_decision(
        decision_id=did,
        organization_id=oid,
        resolve_status="rejected",
        resolver_user_id=1,
        resolver_role_name="owner",
    )
    assert out["ok"] is True
    assert out["status"] == "rejected"
    assert out.get("execution_result") is None
    assert called == []

    with factory() as session:
        row = session.get(AiDecision, did)
        assert row is not None
        assert (row.status or "").lower() == "rejected"


def test_resolve_approved_executes_once(sqlite_ai, monkeypatch: pytest.MonkeyPatch):
    factory, oid = sqlite_ai
    monkeypatch.setattr(ai_decision_store, "get_session_factory", lambda: factory)
    monkeypatch.setattr(system_audit, "record_system_audit", lambda **kwargs: None)

    d = AIDecision(
        action="noop",
        entity="t",
        data={},
        priority="low",
        requires_approval=True,
    )
    ins = ai_decision_store.insert_ai_decision(organization_id=oid, user_id=None, decision=d, status="pending")
    did = int(ins["id"])

    calls = []

    def _exec(**kwargs):
        calls.append(1)
        return {"ok": True, "result": {"message": "ok"}}

    monkeypatch.setattr(ai_decision_store.action_executor, "execute_decision", _exec)

    out = ai_decision_store.resolve_ai_decision(
        decision_id=did,
        organization_id=oid,
        resolve_status="approved",
        resolver_user_id=1,
        resolver_role_name="owner",
    )
    assert out["ok"] is True
    assert out["status"] == "approved"
    assert out["execution_result"]["success"] is True
    assert calls == [1]

    out2 = ai_decision_store.resolve_ai_decision(
        decision_id=did,
        organization_id=oid,
        resolve_status="approved",
        resolver_user_id=1,
        resolver_role_name="owner",
    )
    assert out2.get("idempotent") is True
    assert calls == [1]

    with factory() as session:
        row = session.get(AiDecision, did)
        assert (row.status or "").lower() == "executed"


def test_resolve_approved_execution_failure(sqlite_ai, monkeypatch: pytest.MonkeyPatch):
    factory, oid = sqlite_ai
    monkeypatch.setattr(ai_decision_store, "get_session_factory", lambda: factory)
    monkeypatch.setattr(system_audit, "record_system_audit", lambda **kwargs: None)

    d = AIDecision(
        action="reorder_stock",
        entity="inv",
        data={"sku_name": "X", "quantity": 1, "location": "A"},
        priority="high",
        requires_approval=True,
    )
    ins = ai_decision_store.insert_ai_decision(organization_id=oid, user_id=None, decision=d, status="pending")
    did = int(ins["id"])

    monkeypatch.setattr(
        ai_decision_store.action_executor,
        "execute_decision",
        lambda **kwargs: {"ok": False, "error": "boom"},
    )

    out = ai_decision_store.resolve_ai_decision(
        decision_id=did,
        organization_id=oid,
        resolve_status="approved",
        resolver_user_id=1,
        resolver_role_name="owner",
    )
    assert out["ok"] is True
    assert out["execution_result"]["success"] is False
    assert "boom" in out["execution_result"]["message"]

    with factory() as session:
        row = session.get(AiDecision, did)
        assert (row.status or "").lower() == "failed"
