"""Phase 5: SaaS onboarding, tenant isolation in service layer."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import core.database as core_db
from core.db.base import Base
from core.db.models import Department, Organization, Role, User, UserOrganizationMembership
from services import inventory_phase2_service as inv2
from services import org_service
from services.org_service import create_organization_with_owner


@pytest.fixture
def sqlite_saas(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Organization.__table__,
            Role.__table__,
            Department.__table__,
            User.__table__,
            UserOrganizationMembership.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    monkeypatch.setattr(core_db, "get_session_factory", lambda: factory)
    yield factory
    engine.dispose()


def test_create_organization_with_owner_seeds_units_and_owner(sqlite_saas, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(org_service, "hash_password", lambda p: f"hashed:{p}")
    factory = sqlite_saas
    with factory() as session:
        with session.begin():
            org, user, owner_role = create_organization_with_owner(
                session,
                organization_name="Acme SaaS",
                owner_email="owner@acme.test",
                password="password123",
                plan="pro",
            )
        oid = int(org.id)
        assert org_service.normalize_plan(org.plan) == "pro"
        assert owner_role.name == "owner"
        assert user.email == "owner@acme.test"

    with factory() as session:
        depts = list(
            session.scalars(select(Department).where(Department.organization_id == oid).order_by(Department.name)).all()
        )
        names = {d.name for d in depts}
        assert "General" in names
        assert "Operations" in names
        assert "Sales" in names


@pytest.fixture
def sqlite_inv_two_orgs(monkeypatch: pytest.MonkeyPatch):
    from core.db.models import Inventory, InventoryItem, StockMovement

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Organization.__table__,
            Role.__table__,
            Department.__table__,
            User.__table__,
            UserOrganizationMembership.__table__,
            Inventory.__table__,
            InventoryItem.__table__,
            StockMovement.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    monkeypatch.setattr(core_db, "get_session_factory", lambda: factory)
    monkeypatch.setattr(inv2, "get_session_factory", lambda: factory)
    monkeypatch.setattr(inv2.system_audit, "record_system_audit", lambda **kwargs: None)
    monkeypatch.setenv("SECRET_KEY", "test-secret-saas")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-saas")

    with factory() as session:
        with session.begin():
            org_service.create_organization_with_owner(
                session,
                organization_name="Org A",
                owner_email="a@a.test",
                password="pw",
                plan="free",
            )
            org_service.create_organization_with_owner(
                session,
                organization_name="Org B",
                owner_email="b@b.test",
                password="pw",
                plan="enterprise",
            )
    yield factory
    engine.dispose()


def test_inventory_cannot_mutate_other_org_item(sqlite_inv_two_orgs, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(org_service, "hash_password", lambda p: f"h:{p}")
    factory = sqlite_inv_two_orgs
    with factory() as session:
        with session.begin():
            r = inv2.create_inventory_item_sync(
                organization_id=1,
                sku_name="SECRET-SKU",
                location="L",
                quantity=100,
                reorder_point=1,
                user_id=None,
            )
    assert r.get("ok") is True
    iid = int(r["item"]["id"])

    out = inv2.update_inventory_item_sync(
        organization_id=2,
        item_id=iid,
        quantity=0,
        user_id=None,
    )
    assert out.get("ok") is False
    assert "not found" in (out.get("error") or "").lower()
