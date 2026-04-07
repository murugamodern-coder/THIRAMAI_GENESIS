"""Phase 2: structured billing + production services (SQLite)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import core.database as core_db
from core.db.base import Base
from core.db.models import (
    Asset,
    Equipment,
    GstRecord,
    Invoice,
    InvoiceItem,
    MaintenanceLog,
    Organization,
    Payment,
    ProductionLog,
    RawMaterial,
)
from services import billing_phase2_service as bill2
from services import production_phase2_service as prod2


@pytest.fixture
def sqlite_bp(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Organization.__table__,
            Asset.__table__,
            Invoice.__table__,
            InvoiceItem.__table__,
            Payment.__table__,
            GstRecord.__table__,
            ProductionLog.__table__,
            Equipment.__table__,
            MaintenanceLog.__table__,
            RawMaterial.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as s:
        with s.begin():
            s.add(Organization(id=1, name="O", plan="free"))
            s.flush()
            s.add(
                Asset(
                    id=1,
                    organization_id=1,
                    name="Line",
                    category="machine",
                )
            )
            s.flush()
            s.add(
                Equipment(
                    organization_id=1,
                    name="Extruder",
                    status="Running",
                )
            )
            s.flush()
            s.add(
                RawMaterial(
                    organization_id=1,
                    name="Resin",
                    unit="kg",
                    quantity_on_hand=Decimal("100"),
                )
            )

    monkeypatch.setattr(bill2, "get_session_factory", lambda: factory)
    monkeypatch.setattr(prod2, "get_session_factory", lambda: factory)
    monkeypatch.setattr(core_db, "get_session_factory", lambda: factory)
    monkeypatch.setattr(bill2.system_audit, "record_system_audit", lambda **_: None)
    monkeypatch.setattr(prod2.system_audit, "record_system_audit", lambda **_: None)
    yield factory, 1
    engine.dispose()


def test_structured_invoice_payment_gst(sqlite_bp):
    factory, oid = sqlite_bp
    inv = bill2.create_structured_invoice_sync(
        organization_id=oid,
        invoice_no="T-1",
        invoice_date=date(2026, 1, 10),
        lines=[
            {
                "description": "Widget",
                "quantity": 2,
                "unit_price_pre_tax": 100,
                "gst_rate_percent": 18,
            }
        ],
        user_id=None,
    )
    assert inv["ok"] is True
    iid = int(inv["invoice_id"])

    pay = bill2.record_payment_sync(
        organization_id=oid,
        invoice_id=iid,
        amount_inr=236,
        paid_at=datetime(2026, 1, 11, 12, 0, tzinfo=timezone.utc),
        user_id=None,
    )
    assert pay["ok"] is True

    with factory() as s:
        row = s.get(Invoice, iid)
        assert row is not None
        assert row.payment_status == "paid"

    rep = bill2.gst_report_sync(
        organization_id=oid,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        user_id=None,
    )
    assert rep["ok"] is True
    assert rep["report"]["invoice_count"] >= 1


def test_production_log_and_summary(sqlite_bp):
    _, oid = sqlite_bp
    out = prod2.create_production_log_sync(
        organization_id=oid,
        asset_id=1,
        yield_out=1.5,
        user_id=None,
    )
    assert out["ok"] is True

    summ = prod2.production_summary_sync(organization_id=oid)
    assert summ["ok"] is True
    assert summ["log_count"] >= 1

    machines = prod2.list_machines_sync(organization_id=oid)
    assert machines["ok"] is True
    assert len(machines["machines"]) == 1

    mid = int(machines["machines"][0]["id"])
    m = prod2.create_maintenance_log_sync(
        organization_id=oid,
        equipment_id=mid,
        issue_description="Bearing noise",
        cost=500,
        user_id=None,
    )
    assert m["ok"] is True
