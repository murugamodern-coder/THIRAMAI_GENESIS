"""
Integration tests: mock AI ``sell_stock`` intent -> ``execute_sell_stock_sync`` -> DB assertions.

Uses in-memory SQLite with a minimal table subset (no PostgreSQL required).
"""

from __future__ import annotations

import os
import tempfile
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from core.brain_output import parse_action_intent_dict
from core.db.base import Base
from core.db.models import Bill, FactoryBillingHold, Inventory, Organization
from services.sale_execution import execute_sell_stock_sync


@pytest.fixture
def sqlite_org_and_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"autocommit": False},
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Organization.__table__,
            FactoryBillingHold.__table__,
            Inventory.__table__,
            Bill.__table__,
        ],
    )
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as s:
        # SQLite + BigInteger autoincrement can omit id; set explicitly for stable tests.
        s.add(Organization(id=1, name="Acme", plan="free"))
        s.commit()
        oid = 1
        s.add(
            Inventory(
                id=1,
                organization_id=oid,
                sku_name="Item A",
                quantity=Decimal("10"),
                location="",
                unit_price=Decimal("100.00"),
                gst_rate_percent=Decimal("18.00"),
            )
        )
        s.commit()

    def factory():
        return SessionLocal()

    return oid, factory


def test_mock_ai_sell_intent_reduces_stock_and_creates_bill(sqlite_org_and_factory):
    """Simulate validated LLM output: sell_stock -> sale service -> bill row."""
    org_id, factory = sqlite_org_and_factory
    intent = parse_action_intent_dict(
        {"kind": "sell_stock", "sku_name": "Item A", "quantity": 2, "location": ""}
    )
    assert intent.kind == "sell_stock"

    out = execute_sell_stock_sync(
        org_id,
        intent.sku_name,
        float(intent.quantity),
        intent.location or "",
        _session_factory=factory,
    )
    assert out["ok"] is True
    assert out["bill_id"] >= 1
    # 2 × ₹100 taxable + 18% GST = ₹200 + ₹36 = ₹236
    assert out["total_amount"] == pytest.approx(236.0)
    assert out["remaining_quantity"] == pytest.approx(8.0)

    with factory() as s:
        inv = s.execute(select(Inventory).where(Inventory.sku_name == "Item A")).scalar_one()
        assert float(inv.quantity) == pytest.approx(8.0)
        bill = s.get(Bill, out["bill_id"])
        assert bill is not None
        assert len(bill.items) == 1
        assert bill.items[0]["sku_name"] == "Item A"
        assert bill.items[0]["taxable_value"] == pytest.approx(200.0)
        assert bill.items[0]["gst_total"] == pytest.approx(36.0)
        assert float(bill.total_amount) == pytest.approx(236.0)


def test_gst_one_unit_total_118(sqlite_org_and_factory):
    org_id, factory = sqlite_org_and_factory
    out = execute_sell_stock_sync(org_id, "Item A", 1.0, "", _session_factory=factory)
    assert out["ok"] is True
    assert out["total_amount"] == pytest.approx(118.0)
    assert out["items"][0]["cgst"] == pytest.approx(9.0)
    assert out["items"][0]["sgst"] == pytest.approx(9.0)


def test_interstate_uses_igst_not_cgst_sgst(sqlite_org_and_factory):
    org_id, factory = sqlite_org_and_factory
    out = execute_sell_stock_sync(
        org_id, "Item A", 1.0, "", interstate_gst=True, _session_factory=factory
    )
    assert out["ok"] is True
    assert out["total_amount"] == pytest.approx(118.0)
    assert out["items"][0]["igst"] == pytest.approx(18.0)
    assert out["items"][0]["cgst"] == pytest.approx(0.0)
    assert out["items"][0]["sgst"] == pytest.approx(0.0)


def test_fractional_quantity_rejected_cleanly(sqlite_org_and_factory):
    org_id, factory = sqlite_org_and_factory
    out = execute_sell_stock_sync(org_id, "Item A", 0.5, "", _session_factory=factory)
    assert out["ok"] is False
    assert "fractional" in (out.get("error") or "").lower()


def test_negative_quantity_rejected(sqlite_org_and_factory):
    org_id, factory = sqlite_org_and_factory
    out = execute_sell_stock_sync(org_id, "Item A", -5.0, "", _session_factory=factory)
    assert out["ok"] is False


def test_sell_stock_pydantic_rejects_fractional_quantity():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="whole"):
        parse_action_intent_dict(
            {"kind": "sell_stock", "sku_name": "X", "quantity": 0.5, "location": ""}
        )


def test_concurrent_last_unit_only_one_succeeds():
    """Two threads selling the last single unit: one wins, one gets insufficient stock."""
    import threading

    fd, path = tempfile.mkstemp(suffix="_concurrent.sqlite")
    os.close(fd)
    engine = None
    try:
        engine = create_engine(
            f"sqlite+pysqlite:///{path.replace(os.sep, '/')}",
            connect_args={
                "check_same_thread": False,
                "timeout": 60,
                "autocommit": False,
            },
            pool_pre_ping=True,
        )
        Base.metadata.create_all(
            bind=engine,
            tables=[
                Organization.__table__,
                FactoryBillingHold.__table__,
                Inventory.__table__,
                Bill.__table__,
            ],
        )
        SessionLocal = sessionmaker(bind=engine)
        with SessionLocal() as s:
            s.add(Organization(id=1, name="Acme", plan="free"))
            s.add(
                Inventory(
                    id=1,
                    organization_id=1,
                    sku_name="LastUnit",
                    quantity=Decimal("1"),
                    location="",
                    unit_price=Decimal("50.00"),
                    gst_rate_percent=Decimal("0"),
                )
            )
            s.commit()

        results: list[dict] = []
        lock = threading.Lock()

        def worker():
            out = execute_sell_stock_sync(1, "LastUnit", 1.0, "", _session_factory=SessionLocal)
            with lock:
                results.append(out)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        oks = [r for r in results if r.get("ok")]
        fails = [r for r in results if not r.get("ok")]
        assert len(oks) == 1
        assert len(fails) == 1
        assert "Insufficient" in (fails[0].get("error") or "") or "stock" in (
            fails[0].get("error") or ""
        ).lower()
    finally:
        if engine is not None:
            engine.dispose()
        try:
            os.unlink(path)
        except OSError:
            pass


def test_insufficient_stock_returns_error_not_exception(sqlite_org_and_factory):
    org_id, factory = sqlite_org_and_factory
    out = execute_sell_stock_sync(org_id, "Item A", 50.0, "", _session_factory=factory)
    assert out["ok"] is False
    assert "Insufficient" in (out.get("error") or "")

    with factory() as s:
        inv = s.execute(select(Inventory).where(Inventory.sku_name == "Item A")).scalar_one()
        assert float(inv.quantity) == pytest.approx(10.0)
        n_bills = s.execute(select(Bill)).scalars().all()
        assert len(n_bills) == 0


def test_ambiguous_sku_without_location_returns_error(sqlite_org_and_factory):
    """Two rows same SKU different locations → must not pick arbitrarily or crash."""
    org_id, factory = sqlite_org_and_factory
    with factory() as s:
        s.add(
            Inventory(
                id=2,
                organization_id=org_id,
                sku_name="DupSKU",
                quantity=Decimal("5"),
                location="A",
                unit_price=Decimal("1.00"),
            )
        )
        s.add(
            Inventory(
                id=3,
                organization_id=org_id,
                sku_name="DupSKU",
                quantity=Decimal("5"),
                location="B",
                unit_price=Decimal("1.00"),
            )
        )
        s.commit()
    out = execute_sell_stock_sync(org_id, "DupSKU", 1.0, "", _session_factory=factory)
    assert out["ok"] is False
    assert "ambiguous" in (out.get("error") or "").lower()


def test_unknown_sku_returns_error(sqlite_org_and_factory):
    org_id, factory = sqlite_org_and_factory
    out = execute_sell_stock_sync(org_id, "Ghost SKU", 1.0, "", _session_factory=factory)
    assert out["ok"] is False
    assert "not found" in (out.get("error") or "").lower()


def test_sale_intent_heuristic_parses_simple_phrase():
    from core.sale_intent_heuristic import parsed_sell_intent_from_message

    h = parsed_sell_intent_from_message("Sell 2 units of Item A.")
    assert h is not None
    assert h.quantity == 2.0
    assert "Item A" in h.sku_name


def test_early_veto_fractional_without_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    from brain import run_brain

    r = run_brain("Sell 0.5 units of Soap", 1, actor_role_name="staff")
    assert r.action_intent.kind == "none"
    assert "fractional" in r.narrative.lower() or "whole" in r.narrative.lower()


def test_early_veto_negative_without_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    from brain import run_brain

    r = run_brain("Sell -5 units of Soap", 1, actor_role_name="staff")
    assert r.action_intent.kind == "none"
    assert "negative" in r.narrative.lower()
