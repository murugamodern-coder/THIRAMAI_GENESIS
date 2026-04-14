"""Part E: website templates, static build, deploy slug validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import core.database as core_db
from core.db.base import Base
from core.db.models import GeneratedWebsite, InventoryItem, Organization, Role, User, UserOrganizationMembership
from services import website_db_service as wdb
from services import website_builder_service as wb_mod
from services.website_builder_service import (
    build_website_sync,
    inline_static_assets_for_iframe,
    read_site_iframe_preview_sync,
    slugify_org_name,
    user_can_access_org_sync,
)
from services.website_deploy_service import deploy_site_sync
from services.website_template_service import TEMPLATE_TYPES, get_template_bundle


@pytest.fixture
def sqlite_site_builder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
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
            User.__table__,
            UserOrganizationMembership.__table__,
            InventoryItem.__table__,
            GeneratedWebsite.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    monkeypatch.setattr(core_db, "get_session_factory", lambda: factory)
    monkeypatch.setattr(wdb, "get_session_factory", lambda: factory)
    monkeypatch.setattr(wb_mod, "get_session_factory", lambda: factory)

    sites = tmp_path / "sites"
    sites.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("THIRAMAI_SITES_ROOT", str(sites))

    with factory() as session:
        with session.begin():
            org = Organization(name="Modern Corporation", plan="free", industry="Hardware")
            session.add(org)
            session.flush()
            oid = int(org.id)
            role = Role(organization_id=oid, name="owner", level=1)
            session.add(role)
            session.flush()
            user = User(email="owner@modern.test", password_hash="x", is_active=True)
            session.add(user)
            session.flush()
            uid = int(user.id)
            session.add(
                UserOrganizationMembership(
                    user_id=uid,
                    organization_id=oid,
                    role_id=int(role.id),
                    is_active=True,
                )
            )
            session.add(
                InventoryItem(
                    organization_id=oid,
                    sku_name="Steel Rod 10mm",
                    quantity=__import__("decimal").Decimal("42"),
                    location="Main",
                    unit="pcs",
                    unit_price=__import__("decimal").Decimal("120"),
                )
            )

    yield factory, oid, uid
    engine.dispose()


def test_slugify_org_name_stable():
    s = slugify_org_name("Modern Corporation!!", 99)
    assert s.endswith("-99")
    assert "modern" in s


def test_template_types_and_bundle():
    assert "shop" in TEMPLATE_TYPES
    b = get_template_bundle("shop")
    assert "Steel" not in b["html"]
    assert "hero" in b["html"].lower()


def test_build_writes_index_and_inline_preview(sqlite_site_builder):
    factory, oid, uid = sqlite_site_builder
    out = build_website_sync(oid, "shop", user_id=uid, run_deploy=False)
    assert out.get("ok") is True
    disk = Path(out["disk_path"])
    assert (disk / "index.html").is_file()
    html = (disk / "index.html").read_text(encoding="utf-8")
    assert "Modern Corporation" in html
    assert "Steel Rod" in html

    inlined = inline_static_assets_for_iframe(html, disk)
    assert "<style>" in inlined
    assert "system-ui" in inlined

    pv = read_site_iframe_preview_sync(oid, user_id=uid)
    assert pv.get("ok") is True
    assert "Modern Corporation" in pv["html"]


def test_user_cannot_access_other_org(sqlite_site_builder):
    factory, oid, uid = sqlite_site_builder
    with factory() as session:
        with session.begin():
            org2 = Organization(name="Other Co", plan="free")
            session.add(org2)
            session.flush()
            oid2 = int(org2.id)
    assert user_can_access_org_sync(user_id=uid, organization_id=oid) is True
    assert user_can_access_org_sync(user_id=uid, organization_id=oid2) is False


def test_deploy_rejects_bad_slug():
    assert deploy_site_sync("../etc/passwd").get("ok") is False


def test_generated_website_upsert(sqlite_site_builder):
    factory, oid, uid = sqlite_site_builder
    build_website_sync(oid, "services", user_id=uid, run_deploy=False)
    with factory() as session:
        row = session.execute(select(GeneratedWebsite).where(GeneratedWebsite.organization_id == oid)).scalar_one()
        assert row.template_type == "services"
