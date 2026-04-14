"""Product journey: plans, bootstrap hints, wow insights (new user simulation)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from core.db.base import Base
from core.db.models import Organization, PersonalExpense, PersonalMission, User
import services.product_onboarding_service as product_onboarding
from services.product_onboarding_service import build_wow_insights_sync, get_bootstrap_sync, save_product_profile
from services.product_plans import plan_allows, static_plans_catalog


@pytest.fixture
def sqlite_product_user(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Organization.__table__,
            User.__table__,
            PersonalExpense.__table__,
            PersonalMission.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    monkeypatch.setattr(product_onboarding, "get_session_factory", lambda: factory)

    with factory() as session:
        with session.begin():
            org = Organization(name="Test Org", plan="free")
            session.add(org)
            session.flush()
            u = User(
                email="journey@test.local",
                password_hash="x",
                product_profile={"onboarding": {"insights_done": False}, "wow_shown": False},
            )
            session.add(u)
            session.flush()
            uid = int(u.id)
            oid = int(org.id)

    yield factory, uid, oid
    engine.dispose()


def test_plan_catalog_and_gating():
    ids = {p["id"] for p in static_plans_catalog()}
    assert ids >= {"free", "pro", "business"}
    assert plan_allows("free", "deep_research") is False
    assert plan_allows("free", "auto_accounting") is False
    assert plan_allows("free", "advanced_ai") is False
    assert plan_allows("pro", "deep_research") is True
    assert plan_allows("business", "advanced_ai") is True


def test_bootstrap_wow_pending_then_ack(sqlite_product_user):
    factory, uid, oid = sqlite_product_user
    b1 = get_bootstrap_sync(user_id=uid, organization_id=oid)
    assert b1["ok"] is True
    assert b1["hints"]["wow_pending"] is True

    with factory() as session:
        with session.begin():
            save_product_profile(session, uid, {"wow_shown": True})

    b2 = get_bootstrap_sync(user_id=uid, organization_id=oid)
    assert b2["hints"]["wow_pending"] is False


def test_wow_insights_returns_three(sqlite_product_user):
    factory, uid, oid = sqlite_product_user
    with factory() as session:
        with session.begin():
            session.add(
                PersonalExpense(
                    user_id=uid,
                    currency="INR",
                    category="Travel",
                    subcategory="fuel",
                    spent_at=datetime.now(timezone.utc),
                    title="Fuel",
                    amount=Decimal("1200.00"),
                )
            )
            session.add(
                PersonalMission(
                    user_id=uid,
                    title="Close one invoice",
                    description="Follow up",
                    status="open",
                    priority="P1",
                )
            )

    out = build_wow_insights_sync(user_id=uid, organization_id=oid)
    assert out["ok"] is True
    assert len(out["insights"]) == 3
    assert all("title" in x for x in out["insights"])

    with factory() as session:
        c = session.scalar(
            select(func.count()).select_from(PersonalExpense).where(PersonalExpense.user_id == uid)
        )
        assert int(c or 0) >= 1
