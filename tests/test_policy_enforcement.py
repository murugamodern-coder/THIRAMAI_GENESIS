"""Policy kernel + audit wiring: inventory sell must BLOCK low-privilege principals."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.dependencies import CurrentUser, get_current_user
from core.auth import create_access_token
from core.db.base import Base
from core.db.models import Bill, FactoryBillingHold, Inventory, Organization
import services.sale_execution as sale_execution_mod

from main import app
from services.sale_execution import execute_sell_stock_sync


@pytest.fixture
def sqlite_org_inventory():
    # Single shared connection so ``TestClient`` threads see the same :memory: schema.
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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
        s.commit()
        s.add(
            Inventory(
                id=1,
                organization_id=1,
                sku_name="PolicySKU",
                quantity=Decimal("10"),
                location="",
                unit_price=Decimal("100.00"),
                gst_rate_percent=Decimal("18.00"),
            )
        )
        s.commit()

    def factory():
        return SessionLocal()

    return 1, factory


@pytest.fixture(autouse=True)
def _policy_test_env(monkeypatch: pytest.MonkeyPatch, sqlite_org_inventory):
    monkeypatch.setenv("SECRET_KEY", "test-secret-policy-enforcement")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-policy-enforcement")
    monkeypatch.setenv("THIRAMAI_AUTH_DISABLED", "0")
    _, factory = sqlite_org_inventory

    def _fake_get_session_factory():
        return factory

    # Patch where ``sale_execution`` binds the name (``from core.database import``).
    monkeypatch.setattr(sale_execution_mod, "get_session_factory", _fake_get_session_factory)
    yield
    app.dependency_overrides.clear()


def test_sell_stock_403_when_policy_blocks_customer_role(sqlite_org_inventory):
    """Customer-level role cannot mutate stock — ``inventory.sell_stock`` → BLOCK → HTTP 403."""
    org_id, factory = sqlite_org_inventory
    with pytest.raises(HTTPException) as excinfo:
        execute_sell_stock_sync(
            org_id,
            "PolicySKU",
            1.0,
            "",
            _session_factory=factory,
            principal_user_id=42,
            principal_role_level=5,
            correlation_id="corr-policy-test-1",
        )
    assert excinfo.value.status_code == 403
    assert "operational" in (excinfo.value.detail or "").lower()

    with factory() as s:
        inv = s.execute(select(Inventory).where(Inventory.sku_name == "PolicySKU")).scalar_one()
        assert float(inv.quantity) == pytest.approx(10.0)


def test_retail_sell_endpoint_403_customer_jwt(sqlite_org_inventory):
    """HTTP path: JWT customer calling ``POST /inventory/retail-sell`` gets 403 from policy engine."""

    async def _customer() -> CurrentUser:
        return CurrentUser(
            id=77,
            email="cust-policy@test.local",
            organization_id=1,
            role_name="customer",
            role_level=5,
            is_active=True,
        )

    app.dependency_overrides[get_current_user] = _customer
    token = create_access_token(sub_user_id=77, org_id=1, role_name="customer")
    client = TestClient(app)
    r = client.post(
        "/inventory/retail-sell",
        json={"sku_name": "PolicySKU", "quantity": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
    body = r.json()
    assert "detail" in body
    assert "operational" in str(body.get("detail", "")).lower()

    _, factory = sqlite_org_inventory
    with factory() as s:
        inv = s.execute(select(Inventory).where(Inventory.sku_name == "PolicySKU")).scalar_one()
        assert float(inv.quantity) == pytest.approx(10.0)


def test_retail_sell_owner_allowed_when_policy_allows(sqlite_org_inventory):
    """Owner/manager (level ≤2) gets ALLOW on HIGH-risk ``inventory.sell_stock`` and mutates stock."""

    async def _owner() -> CurrentUser:
        return CurrentUser(
            id=3,
            email="owner-policy@test.local",
            organization_id=1,
            role_name="owner",
            role_level=1,
            is_active=True,
        )

    app.dependency_overrides[get_current_user] = _owner
    token = create_access_token(
        sub_user_id=3,
        org_id=1,
        role_name="owner",
        expires_delta=timedelta(hours=1),
    )
    client = TestClient(app)
    r = client.post(
        "/inventory/retail-sell",
        json={"sku_name": "PolicySKU", "quantity": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    assert data.get("remaining_quantity") == pytest.approx(9.0)
