"""Phase 2: enterprise inventory service + RBAC on HTTP routes."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import core.database as core_db
from api.dependencies import CurrentUser, get_current_user
from core.auth import create_access_token
from core.db.base import Base
from core.db.models import (
    Inventory,
    InventoryItem,
    Organization,
    PurchaseOrder,
    PurchaseOrderLine,
    StockMovement,
    Supplier,
)
from main import app
from services import inventory_phase2_service as inv2


@pytest.fixture
def sqlite_inv2(monkeypatch: pytest.MonkeyPatch):
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
            Supplier.__table__,
            PurchaseOrder.__table__,
            PurchaseOrderLine.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as s:
        with s.begin():
            s.add(Organization(id=1, name="Org1", plan="free"))
            s.flush()
    monkeypatch.setattr(inv2, "get_session_factory", lambda: factory)
    monkeypatch.setattr(core_db, "get_session_factory", lambda: factory)
    monkeypatch.setenv("SECRET_KEY", "test-secret-phase2-inv")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-phase2-inv")
    monkeypatch.setenv("THIRAMAI_AUTH_DISABLED", "0")
    yield factory, 1
    app.dependency_overrides.clear()
    engine.dispose()


def test_create_list_movement_and_legacy_mirror(sqlite_inv2, monkeypatch: pytest.MonkeyPatch):
    factory, oid = sqlite_inv2
    monkeypatch.setattr(inv2.system_audit, "record_system_audit", lambda **_: None)

    r = inv2.create_inventory_item_sync(
        organization_id=oid,
        sku_name="SKU-A",
        location="WH1",
        quantity=5,
        unit_price=10,
        reorder_point=2,
        user_id=None,
    )
    assert r["ok"] is True
    iid = r["item"]["id"]

    with factory() as s:
        leg = s.execute(select(Inventory).where(Inventory.sku_name == "SKU-A")).scalar_one_or_none()
        assert leg is not None
        assert float(leg.quantity) == pytest.approx(5.0)

    m = inv2.record_stock_movement_sync(
        organization_id=oid,
        inventory_item_id=iid,
        quantity_delta=-2,
        movement_type="OUT",
        user_id=None,
    )
    assert m["ok"] is True
    assert m["item"]["quantity"] == pytest.approx(3.0)

    lst = inv2.list_inventory_items_sync(organization_id=oid)
    assert lst["ok"] is True
    assert len(lst["items"]) == 1


def test_low_stock_alert(sqlite_inv2, monkeypatch: pytest.MonkeyPatch):
    factory, oid = sqlite_inv2
    monkeypatch.setattr(inv2.system_audit, "record_system_audit", lambda **_: None)
    inv2.create_inventory_item_sync(
        organization_id=oid,
        sku_name="LOW",
        location="",
        quantity=1,
        reorder_point=5,
        user_id=None,
    )
    alerts = inv2.list_low_stock_alerts_sync(organization_id=oid)
    assert alerts["ok"] is True
    assert len(alerts["alerts"]) == 1
    assert alerts["alerts"][0]["alert_reason"] == "at_or_below_reorder_point"


def test_po_supplier_receive(sqlite_inv2, monkeypatch: pytest.MonkeyPatch):
    factory, oid = sqlite_inv2
    monkeypatch.setattr(inv2.system_audit, "record_system_audit", lambda **_: None)

    sup = inv2.create_supplier_sync(organization_id=oid, name="Vend", user_id=None)
    assert sup["ok"] is True
    sid = sup["supplier"]["id"]

    po = inv2.create_purchase_order_sync(
        organization_id=oid,
        supplier_id=sid,
        order_date=date(2026, 1, 15),
        lines=[{"sku_name": "RAW-X", "quantity_ordered": 10, "unit_cost_pre_tax": 5}],
        user_id=None,
    )
    assert po["ok"] is True
    pid = po["purchase_order"]["id"]

    with factory() as s:
        line = s.execute(
            select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == pid)
        ).scalar_one()
        lid = int(line.id)

    rcv = inv2.receive_purchase_order_line_sync(
        organization_id=oid,
        purchase_order_id=pid,
        line_id=lid,
        quantity=10,
        inventory_location="DOCK",
        user_id=None,
    )
    assert rcv["ok"] is True
    assert rcv["purchase_order_status"] == "received"
    assert rcv["item"]["quantity"] == pytest.approx(10.0)


def test_get_inventory_403_customer(sqlite_inv2):
    _, _oid = sqlite_inv2

    async def _customer() -> CurrentUser:
        return CurrentUser(
            id=9,
            email="c@test.local",
            organization_id=1,
            role_name="customer",
            role_level=5,
            is_active=True,
        )

    app.dependency_overrides[get_current_user] = _customer
    token = create_access_token(sub_user_id=9, org_id=1, role_name="customer")
    client = TestClient(app)
    r = client.get("/inventory", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_get_inventory_200_worker(sqlite_inv2):
    _, _oid = sqlite_inv2

    async def _worker() -> CurrentUser:
        return CurrentUser(
            id=10,
            email="w@test.local",
            organization_id=1,
            role_name="worker",
            role_level=4,
            is_active=True,
        )

    app.dependency_overrides[get_current_user] = _worker
    token = create_access_token(sub_user_id=10, org_id=1, role_name="worker")
    client = TestClient(app)
    r = client.get("/inventory", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
    assert "items" in body
