"""Intent engine + tool executor (heuristics, veto, read snapshot)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.db.base import Base
from core.db.models import Inventory, Organization
from core.intent_engine import resolve_intent
from core.tool_executor import execute_intent
import services.sale_execution as sale_execution_mod


@pytest.fixture
def sqlite_inv():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[Organization.__table__, Inventory.__table__],
    )
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as s:
        s.add(Organization(id=1, name="Acme", plan="free"))
        s.commit()
        s.add(
            Inventory(
                id=1,
                organization_id=1,
                sku_name="pvc pipe",
                quantity=Decimal("100"),
                location="",
                unit_price=Decimal("10.00"),
                gst_rate_percent=Decimal("18"),
            ),
        )
        s.commit()

    def factory():
        return SessionLocal()

    return 1, factory


@pytest.fixture(autouse=True)
def _patch_factory(monkeypatch: pytest.MonkeyPatch, sqlite_inv):
    _, factory = sqlite_inv

    def _fake():
        return factory

    monkeypatch.setattr(sale_execution_mod, "get_session_factory", _fake)
    monkeypatch.setattr("core.tool_executor.get_session_factory", _fake)
    monkeypatch.setattr("core.database.get_session_factory", _fake)
    monkeypatch.setattr("services.analytics_service.get_session_factory", _fake)
    yield


def test_resolve_add_and_sell_heuristic():
    a = resolve_intent("Add 20 pvc pipe", skip_llm=True)
    assert a["intent"] == "add_inventory"
    assert "pvc" in a["entity"].lower()
    assert a["quantity"] == 20.0

    s = resolve_intent("Sell 5 soap", skip_llm=True)
    assert s["intent"] == "sell_inventory"
    assert s["quantity"] == 5.0
    assert "soap" in s["entity"].lower()


def test_resolve_show_inventory():
    r = resolve_intent("Show inventory", skip_llm=True)
    assert r["intent"] == "read_inventory"


def test_execute_sell_negative_rejected(sqlite_inv):
    oid, _ = sqlite_inv
    out = execute_intent(
        {"intent": "sell_inventory", "entity": "x", "quantity": -10, "source": "test"},
        {"organization_id": oid, "role_level": 1, "user_message": "Sell -10 item"},
    )
    assert out["ok"] is False
    assert out["status"] == "error"


def test_veto_message_dashboard_unknown_path(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-import")
    from unittest.mock import patch

    from services.dashboard_command_executor import _execute_natural_language_dashboard_command_raw

    with patch("services.dashboard_command_executor._groq_extract_structured") as m:
        m.return_value = {
            "action": "unknown",
            "entity_name": "",
            "value": "",
            "numeric_value": None,
            "confidence": 0.1,
            "rationale": "test",
        }
        out = _execute_natural_language_dashboard_command_raw(
            raw_command="Sell -10 soap",
            organization_id=1,
            sre_profile="development",
        )
    assert out.get("error") == "retail_quantity_veto"
    assert "Cannot process sale" in (out.get("thought_message") or "")


def test_add_inventory_execute(sqlite_inv):
    oid, _ = sqlite_inv
    out = execute_intent(
        {
            "intent": "add_inventory",
            "entity": "pvc pipe",
            "quantity": 5.0,
            "source": "test",
        },
        {"organization_id": oid},
    )
    assert out["ok"] is True
    assert out["action"] == "add_inventory"
    assert out["data"].get("new_quantity") == 105.0


def test_read_inventory_snapshot(sqlite_inv):
    oid, _ = sqlite_inv
    out = execute_intent(
        {"intent": "read_inventory", "read_mode": "snapshot", "source": "test"},
        {"organization_id": oid},
    )
    assert out["ok"] is True
    assert out["data"].get("count") == 1
