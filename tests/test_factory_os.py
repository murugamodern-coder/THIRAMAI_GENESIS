"""Factory OS: project engine, billing guard, revival cost math."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import core.database as core_db
from core.db.base import Base
from core.db.models import (
    Asset,
    Bill,
    Equipment,
    FactoryBillingHold,
    Inventory,
    Organization,
    ProjectStaffAssignment,
    ProjectStage,
    Role,
    User,
    UserOrganizationMembership,
)
from services import billing_guard, maintenance_service, project_engine
from services.sale_execution import execute_sell_stock_sync


@pytest.fixture
def sqlite_factory(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Organization.__table__,
            Role.__table__,
            User.__table__,
            UserOrganizationMembership.__table__,
            Asset.__table__,
            FactoryBillingHold.__table__,
            ProjectStage.__table__,
            ProjectStaffAssignment.__table__,
            Inventory.__table__,
            Bill.__table__,
            Equipment.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as s:
        with s.begin():
            org = Organization(id=1, name="T", plan="free")
            s.add(org)
            s.flush()
            role = Role(id=1, organization_id=int(org.id), name="owner", level=1)
            s.add(role)
            s.flush()
            u = User(
                id=1,
                email="o@test.local",
                password_hash="x",
            )
            s.add(u)
            s.flush()
            s.add(
                UserOrganizationMembership(
                    user_id=int(u.id),
                    organization_id=int(org.id),
                    role_id=int(role.id),
                    is_active=True,
                )
            )
            s.flush()
            ast = Asset(
                id=1,
                organization_id=int(org.id),
                name="Line-A",
                category="machine",
                valuation=Decimal("100000"),
            )
            s.add(ast)
            s.flush()
            oid = int(org.id)
            aid = int(ast.id)
            uid = int(u.id)
    monkeypatch.setattr(core_db, "get_session_factory", lambda: factory)
    monkeypatch.setattr(billing_guard, "get_session_factory", lambda: factory)
    monkeypatch.setattr(project_engine, "get_session_factory", lambda: factory)
    monkeypatch.setattr(maintenance_service, "get_session_factory", lambda: factory)
    yield factory, oid, aid, uid
    engine.dispose()


def test_stage_labels():
    assert "Income" in project_engine.stage_label(ProjectStage.STAGE_INCOME)


def test_revival_cost_estimate_from_asset(sqlite_factory):
    factory, oid, aid, _ = sqlite_factory
    with factory() as s:
        p = ProjectStage(
            organization_id=oid,
            project_name="Solar",
            current_stage=ProjectStage.STAGE_REPAIR,
            status="active",
            asset_id=aid,
            revival_cost_inr=None,
        )
        s.add(p)
        s.commit()
        s.refresh(p)
        est = project_engine.estimate_revival_cost_inr(p, s)
        assert est == Decimal("10000.00")


def test_billing_guard_roundtrip(sqlite_factory):
    factory, oid, _, _ = sqlite_factory
    assert billing_guard.is_billing_paused(oid) is False
    billing_guard.set_factory_billing_paused(oid, True, reason="test hold")
    assert billing_guard.is_billing_paused(oid) is True
    assert "test hold" in billing_guard.billing_pause_message(oid)


def test_equipment_down_triggers_billing_pause(sqlite_factory):
    """Dry-run: PATCH Down path → org-level factory billing hold (maintenance_service)."""
    factory, oid, _, _ = sqlite_factory
    with factory() as s:
        with s.begin():
            eq = Equipment(organization_id=oid, name="Extruder-A", status="Running")
            s.add(eq)
            s.flush()
            eid = int(eq.id)
    assert billing_guard.is_billing_paused(oid) is False
    ok, msg = maintenance_service.set_equipment_status(
        organization_id=oid,
        equipment_id=eid,
        new_status="Down",
    )
    assert ok is True
    assert msg == "ok"
    assert billing_guard.is_billing_paused(oid) is True
    assert "Extruder-A" in billing_guard.billing_pause_message(oid)


def test_assign_staff_same_org(sqlite_factory):
    factory, oid, _, uid = sqlite_factory
    pid = project_engine.create_project(
        organization_id=oid,
        project_name="P1",
        current_stage=ProjectStage.STAGE_INCOME,
    )
    assert pid is not None
    ok, msg = project_engine.assign_staff(
        project_stage_id=int(pid),
        organization_id=oid,
        user_id=uid,
        role_note="lead",
    )
    assert ok is True


def test_stage2_failure_blocks_sale_and_triggers_emergency_hook(sqlite_factory, monkeypatch):
    """Stage 2 machine failure → billing pause blocks retail sell; emergency notifier runs."""
    factory, oid, _, _ = sqlite_factory
    emergency_calls: list[tuple[int, int, str]] = []

    def _capture_emergency(o: int, p: int, n: str) -> None:
        emergency_calls.append((int(o), int(p), n))

    monkeypatch.setattr(project_engine, "_insert_factory_emergency_notification", _capture_emergency)

    with factory() as s:
        with s.begin():
            s.add(
                Inventory(
                    id=10,
                    organization_id=oid,
                    sku_name="SOLAR-PART",
                    quantity=Decimal("5"),
                    location="",
                    unit_price=Decimal("100.00"),
                    gst_rate_percent=Decimal("0"),
                )
            )
    pid = project_engine.create_project(
        organization_id=oid,
        project_name="Solar Project",
        current_stage=ProjectStage.STAGE_INCOME,
    )
    assert pid is not None
    ok, _ = project_engine.apply_stage2_machine_failure(
        project_stage_id=int(pid), organization_id=oid
    )
    assert ok is True
    assert len(emergency_calls) == 1
    assert emergency_calls[0][0] == oid
    assert emergency_calls[0][1] == int(pid)

    out = execute_sell_stock_sync(oid, "SOLAR-PART", 1.0, "", _session_factory=factory)
    assert out.get("ok") is False
    err = (out.get("error") or "").lower()
    assert (
        "billing" in err
        or "pause" in err
        or "hold" in err
        or "machine failure" in err
        or "stage 2" in err
    )

    with factory() as s:
        n_bills = s.execute(select(Bill)).scalars().all()
    assert len(n_bills) == 0
