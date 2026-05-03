"""Phase 5: bills/inventory analytics and dashboard API (admin gate)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from api.dependencies import CurrentUser, get_current_user
from core.db.base import Base
from core.db.models import Bill, Inventory, Organization
from main import app
from services.analytics_service import (
    compute_dashboard_summary_sync,
    list_low_stock_alerts_sync,
    user_requests_sales_analytics,
)


def _line(sku: str, qty: float, taxable: str, cgst: str, sgst: str, igst: str, grand: str) -> dict:
    return {
        "sku_name": sku,
        "quantity": qty,
        "taxable_value": float(taxable),
        "cgst": float(cgst),
        "sgst": float(sgst),
        "igst": float(igst),
        "line_total_with_tax": float(grand),
    }


@pytest.fixture
def analytics_sqlite_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"autocommit": False},
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[Organization.__table__, Bill.__table__, Inventory.__table__],
    )
    SessionLocal = sessionmaker(bind=engine)
    anchor = datetime(2026, 3, 18, 14, 30, tzinfo=timezone.utc)  # Wednesday
    # Same week Monday = 2026-03-16
    with SessionLocal() as s:
        s.add(Organization(id=1, name="Co", plan="free"))
        s.add(
            Bill(
                organization_id=1,
                items=[_line("ItemA", 1, "100", "9", "9", "0", "118")],
                total_amount=Decimal("118.00"),
                created_at=anchor,
            )
        )
        s.add(
            Bill(
                organization_id=1,
                items=[_line("ItemA", 2, "200", "18", "18", "0", "236")],
                total_amount=Decimal("236.00"),
                created_at=datetime(2026, 3, 17, 10, 0, tzinfo=timezone.utc),
            )
        )
        s.add(
            Bill(
                organization_id=1,
                items=[_line("ItemB", 1, "100", "0", "0", "18", "118")],
                total_amount=Decimal("118.00"),
                created_at=datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc),
            )
        )
        s.add(
            Inventory(
                id=1,
                organization_id=1,
                sku_name="Low1",
                quantity=Decimal("2"),
                location="",
                unit_price=Decimal("10.00"),
            )
        )
        s.add(
            Inventory(
                id=2,
                organization_id=1,
                sku_name="Ok1",
                quantity=Decimal("50"),
                location="",
                unit_price=Decimal("1.00"),
            )
        )
        s.commit()

    def factory():
        return SessionLocal()

    return factory, anchor


def test_revenue_and_gst_windows(analytics_sqlite_factory):
    factory, anchor = analytics_sqlite_factory
    out = compute_dashboard_summary_sync(1, _session_factory=factory, _as_of=anchor)
    assert out["ok"] is True
    assert out["revenue_inr"]["today"] == "118.00"
    assert out["revenue_inr"]["this_week"] == "354.00"
    assert out["revenue_inr"]["this_month"] == "354.00"

    gt = out["gst_collected_inr"]["today"]
    assert gt["cgst"] == "9.00" and gt["sgst"] == "9.00" and gt["igst"] == "0.00"

    gm = out["gst_collected_inr"]["this_month"]
    # Mar18 (9+9) + Mar17 (18+18); February bill excluded from March
    assert gm["cgst"] == "27.00"
    assert gm["sgst"] == "27.00"
    assert gm["igst"] == "0.00"

    tops = {r["sku_name"]: r["quantity_sold"] for r in out["top_selling_products"]}
    assert tops.get("ItemA") == pytest.approx(3.0)
    assert tops.get("ItemB") == pytest.approx(1.0)


def test_low_stock_list(analytics_sqlite_factory):
    factory, _ = analytics_sqlite_factory
    low = list_low_stock_alerts_sync(1, threshold=5, _session_factory=factory)
    assert low["ok"] is True
    skus = [x["sku_name"] for x in low["items"]]
    assert "Low1" in skus
    assert "Ok1" not in skus


def test_sales_analytics_trigger_phrases():
    assert user_requests_sales_analytics("How much did we sell today?") is True
    assert user_requests_sales_analytics("Give me a sales report") is True
    assert user_requests_sales_analytics("Random weather question") is False


@pytest.fixture
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


@patch("api.routes.dashboard.compute_dashboard_summary_sync")
def test_dashboard_summary_admin_ok(mock_compute, _clear_overrides):
    mock_compute.return_value = {
        "ok": True,
        "revenue_inr": {"today": "0.00", "this_week": "0.00", "this_month": "0.00"},
        "gst_collected_inr": {"today": {}, "this_month": {}},
        "top_selling_products": [],
    }
    async def _admin():
        return CurrentUser(
            id=1,
            email="a@t.local",
            organization_id=1,
            role_name="admin",
            role_level=1,
            is_active=True,
        )

    app.dependency_overrides[get_current_user] = _admin
    client = TestClient(app)
    r = client.get("/dashboard/summary")
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is False or "revenue_inr" in body


@patch("api.routes.dashboard.build_command_center_sap_payload_sync")
def test_dashboard_forbidden_for_non_admin(mock_sap_cc, _clear_overrides):
    mock_sap_cc.return_value = {
        "ok": True,
        "organization_id": 1,
        "schema": "thiramai.command_center.sap.v1",
        "life_dashboard": {},
        "analytics": {},
        "inventory_alerts": {"ok": True, "count": 0, "items": []},
        "priority_queue": [],
    }

    async def _owner():
        return CurrentUser(
            id=2,
            email="o@t.local",
            organization_id=1,
            role_name="owner",
            role_level=1,
            is_active=True,
        )

    app.dependency_overrides[get_current_user] = _owner
    client = TestClient(app)
    assert client.get("/dashboard/summary").status_code == 403
    assert client.get("/dashboard/inventory-alerts").status_code == 403
    assert client.get("/dashboard/command-center").status_code == 200


@patch("api.routes.dashboard.build_command_center_sap_payload_sync")
def test_dashboard_command_center_admin_ok(mock_sap, _clear_overrides):
    mock_sap.return_value = {
        "ok": True,
        "organization_id": 1,
        "schema": "thiramai.command_center.sap.v1",
        "life_dashboard": {"top_focus": "x"},
        "priority_tasks": [],
        "proactive_alerts": [],
        "life_context": {},
        "business_summary": {},
        "inventory_summary": {},
        "ai_decisions": {},
        "next_best_move": "",
        "alerts": [],
        "analytics": {"ok": True},
        "inventory_alerts": {"ok": True, "count": 0, "items": []},
        "pending_hitl": [],
        "agenda_open_tasks": [],
        "priority_queue": [],
        "priority_counts": {"emergency": 0, "urgent": 0, "later": 0},
    }

    async def _admin():
        return CurrentUser(
            id=1,
            email="a@t.local",
            organization_id=1,
            role_name="admin",
            role_level=1,
            is_active=True,
        )

    app.dependency_overrides[get_current_user] = _admin
    client = TestClient(app)
    r = client.get("/dashboard/command-center")
    assert r.status_code == 200
    body = r.json()
    assert "priority_queue" in body
    assert "analytics" in body
    assert "life_dashboard" in body
    mock_sap.assert_called_once()
