"""
OWASP A01 — tenant isolation / IDOR regression tests.

Uses in-memory SQLite with the same session factory wired into route dependencies
(``get_session_factory`` is patched on every module that binds it at import time).

**Coverage (extend over time):** inventory (all read + mutating routes in
``api/routes/inventory.py`` used here), ``/audit``, control plane ``/jobs``,
``/alerts``, ``/inventory/reorder``, ``/me/*`` tenancy, ``/analytics/summary``,
and sequential IDOR probes on ``PUT /inventory/item/{id}``.

Cross-tenant writes often return **400** with a generic error from the service
layer (row not found / validation) rather than **403**; that is acceptable when
no other tenant’s data is returned. Assertions reject any **2xx** success on
cross-tenant mutations.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import api.dependencies as api_deps
import api.routes.audit as audit_routes
import api.routes.control_plane as control_plane_routes
import api.routes.tenancy as tenancy_routes
import core.database as core_db
import services.analytics_service as analytics_svc
import services.audit_log as system_audit_mod
import services.billing_guard as billing_guard
import services.inventory_phase2_service as inv2
import services.inventory_service as inv_svc
import services.sale_execution as sale_execution
import services.usage_log_service as usage_log_svc
import workers.alert_system as alert_system
from core.auth import create_access_token
from core.db.base import Base
from core.db.models import (
    AiDecision,
    AuditLog,
    Bill,
    ControlPlaneAlert,
    ControlPlaneJob,
    FactoryBillingHold,
    Inventory,
    InventoryItem,
    Organization,
    PurchaseOrder,
    PurchaseOrderLine,
    Role,
    StockMovement,
    Supplier,
    SupplierPayment,
    UsageLog,
    User,
    UserOrganizationMembership,
)
from main import app
from services import experience_buffer as experience_buffer_mod


TENANT_SCOPE_KEYS = frozenset(
    {
        "organization_id",
        "org_id",
        "active_org_id",
        "active_organization_id",
    }
)


def _walk_assert_no_forbidden_org(obj: Any, forbidden_org_id: int, path: str = "$") -> None:
    """Fail if any tenant-scope field equals ``forbidden_org_id``."""
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            p = f"{path}.{k}"
            if k in TENANT_SCOPE_KEYS and v is not None:
                try:
                    if int(v) == int(forbidden_org_id):
                        raise AssertionError(f"Foreign tenant id leaked at {p}: {v}")
                except (TypeError, ValueError):
                    pass
            _walk_assert_no_forbidden_org(v, forbidden_org_id, p)
    elif isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray)):
        for i, item in enumerate(obj):
            _walk_assert_no_forbidden_org(item, forbidden_org_id, f"{path}[{i}]")


def assert_response_scoped_to_org(
    resp,
    *,
    expected_org_id: int,
    forbidden_org_id: int,
    allow_status: tuple[int, ...] = (200,),
) -> None:
    if resp.status_code not in allow_status:
        return
    try:
        data = resp.json()
    except Exception:
        return
    _walk_assert_no_forbidden_org(data, forbidden_org_id)
    if isinstance(data, Mapping) and "organization_id" in data:
        assert int(data["organization_id"]) == int(expected_org_id)


def assert_no_cross_tenant_success(resp) -> None:
    """Mutations must not succeed (2xx) when targeting another tenant's resources."""
    assert resp.status_code not in (200, 201, 202), resp.text
    assert resp.status_code in (400, 401, 403, 404, 422, 503), resp.text


def _create_sqlite_audit_and_control_plane_tables(engine) -> None:
    """SQLite cannot compile JSONB from models; mirror minimal schemas for route tests."""
    ddl = [
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            action_type VARCHAR(128) NOT NULL,
            entity VARCHAR(128) NOT NULL,
            entity_id VARCHAR(128),
            source VARCHAR(16) NOT NULL,
            result VARCHAR(16) NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS control_plane_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            type VARCHAR(64) NOT NULL,
            message TEXT NOT NULL,
            severity VARCHAR(16) NOT NULL DEFAULT 'warning',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            resolved BOOLEAN NOT NULL DEFAULT 0,
            resolved_at TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS control_plane_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            type VARCHAR(64) NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            status VARCHAR(32) NOT NULL DEFAULT 'scheduled',
            scheduled_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_error TEXT
        )
        """,
    ]
    with engine.begin() as conn:
        for stmt in ddl:
            conn.execute(text(stmt))


def _patch_session_factories(monkeypatch: pytest.MonkeyPatch, factory: sessionmaker) -> None:
    sentinel = lambda: factory  # noqa: E731
    for mod in (
        core_db,
        api_deps,
        inv2,
        inv_svc,
        usage_log_svc,
        sale_execution,
        billing_guard,
        audit_routes,
        control_plane_routes,
        tenancy_routes,
        analytics_svc,
        alert_system,
    ):
        monkeypatch.setattr(mod, "get_session_factory", sentinel)


@pytest.fixture
def tenant_isolation_world(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        Organization.__table__,
        User.__table__,
        Role.__table__,
        UserOrganizationMembership.__table__,
        Inventory.__table__,
        InventoryItem.__table__,
        StockMovement.__table__,
        Supplier.__table__,
        PurchaseOrder.__table__,
        PurchaseOrderLine.__table__,
        SupplierPayment.__table__,
        Bill.__table__,
        FactoryBillingHold.__table__,
        UsageLog.__table__,
        AiDecision.__table__,
    ]
    Base.metadata.create_all(bind=engine, tables=tables)
    _create_sqlite_audit_and_control_plane_tables(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    org_a_id = 1
    org_b_id = 2

    with factory() as s:
        with s.begin():
            s.add_all(
                [
                    Organization(id=org_a_id, name="org_A", plan="free"),
                    Organization(id=org_b_id, name="org_B", plan="free"),
                ]
            )
            s.flush()
            ra = Role(id=1, organization_id=org_a_id, name="owner", level=1)
            rb = Role(id=2, organization_id=org_b_id, name="owner", level=1)
            s.add_all([ra, rb])
            s.flush()
            ua = User(
                id=1,
                email="owner-a@tenant.test",
                password_hash="x",
                is_active=True,
            )
            ub = User(
                id=2,
                email="owner-b@tenant.test",
                password_hash="x",
                is_active=True,
            )
            s.add_all([ua, ub])
            s.flush()
            s.add_all(
                [
                    UserOrganizationMembership(
                        user_id=int(ua.id),
                        organization_id=org_a_id,
                        role_id=int(ra.id),
                        is_active=True,
                    ),
                    UserOrganizationMembership(
                        user_id=int(ub.id),
                        organization_id=org_b_id,
                        role_id=int(rb.id),
                        is_active=True,
                    ),
                ]
            )

    _patch_session_factories(monkeypatch, factory)
    monkeypatch.setenv("SECRET_KEY", "tenant-isolation-test-secret")
    monkeypatch.setenv("JWT_SECRET_KEY", "tenant-isolation-test-secret")
    monkeypatch.setenv("THIRAMAI_AUTH_DISABLED", "0")
    monkeypatch.setattr(inv2.system_audit, "record_system_audit", lambda **_: None)
    monkeypatch.setattr(system_audit_mod, "record_system_audit", lambda **_: None)
    monkeypatch.setattr(experience_buffer_mod, "is_blocked_by_critical_mistake", lambda *_a, **_k: (False, ""))

    with factory() as s:
        with s.begin():
            s.add(
                AuditLog(
                    organization_id=org_b_id,
                    user_id=int(ub.id),
                    action_type="SECRET_B_ACTION",
                    entity="org_b_entity_marker",
                    entity_id="e-b-1",
                    source="USER",
                    result="SUCCESS",
                    audit_metadata={"marker": "ORG_B_AUDIT_SECRET"},
                )
            )
            s.add(
                ControlPlaneAlert(
                    organization_id=org_b_id,
                    type="test",
                    message="ORG_B_CP_ALERT_SECRET",
                    severity="warning",
                    resolved=False,
                )
            )
            s.add(
                ControlPlaneJob(
                    organization_id=org_b_id,
                    type="test_job",
                    payload={"marker": "ORG_B_JOB_SECRET"},
                    status="scheduled",
                )
            )

    monkeypatch.setattr(inv2, "get_session_factory", lambda: factory)
    monkeypatch.setattr(core_db, "get_session_factory", lambda: factory)

    token_a = create_access_token(sub_user_id=1, org_id=org_a_id, role_name="owner", active_org_id=org_a_id)
    token_b = create_access_token(sub_user_id=2, org_id=org_b_id, role_name="owner", active_org_id=org_b_id)

    with factory() as s:
        with s.begin():
            ia = InventoryItem(
                organization_id=org_a_id,
                sku_name="SKU_A_ONLY",
                quantity=Decimal("10"),
                location="L1",
                unit="pcs",
                reorder_point=Decimal("1"),
            )
            ib = InventoryItem(
                organization_id=org_b_id,
                sku_name="SKU_B_ONLY_ORG2",
                quantity=Decimal("20"),
                location="L2",
                unit="pcs",
                reorder_point=Decimal("2"),
            )
            s.add_all([ia, ib])
            s.flush()
            item_a_id = int(ia.id)
            item_b_id = int(ib.id)

            sa = Supplier(organization_id=org_a_id, name="Sup_A")
            sb = Supplier(organization_id=org_b_id, name="Sup_B_ORG2_SECRET")
            s.add_all([sa, sb])
            s.flush()
            sup_a_id = int(sa.id)
            sup_b_id = int(sb.id)

            poa = PurchaseOrder(
                organization_id=org_a_id,
                supplier_id=sup_a_id,
                status="draft",
                order_date=date(2026, 1, 1),
            )
            pob = PurchaseOrder(
                organization_id=org_b_id,
                supplier_id=sup_b_id,
                status="draft",
                order_date=date(2026, 1, 2),
            )
            s.add_all([poa, pob])
            s.flush()
            po_a_id = int(poa.id)
            po_b_id = int(pob.id)

            la = PurchaseOrderLine(
                purchase_order_id=po_a_id,
                sku_name="LINE_A",
                quantity_ordered=Decimal("5"),
                unit_cost_pre_tax=Decimal("1"),
            )
            lb = PurchaseOrderLine(
                purchase_order_id=po_b_id,
                sku_name="LINE_B_ORG2",
                quantity_ordered=Decimal("5"),
                unit_cost_pre_tax=Decimal("1"),
            )
            s.add_all([la, lb])
            s.flush()
            line_a_id = int(la.id)
            line_b_id = int(lb.id)

    ctx = {
        "factory": factory,
        "org_a_id": org_a_id,
        "org_b_id": org_b_id,
        "token_a": token_a,
        "token_b": token_b,
        "item_a_id": item_a_id,
        "item_b_id": item_b_id,
        "sup_a_id": sup_a_id,
        "sup_b_id": sup_b_id,
        "po_a_id": po_a_id,
        "po_b_id": po_b_id,
        "line_a_id": line_a_id,
        "line_b_id": line_b_id,
    }
    yield ctx
    app.dependency_overrides.clear()
    engine.dispose()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestInventoryTenantIsolation:
    def test_get_inventory_list_only_org_a(self, tenant_isolation_world):
        c = tenant_isolation_world
        client = TestClient(app)
        r = client.get("/inventory", headers=_auth(c["token_a"]))
        assert r.status_code == 200
        body = r.json()
        assert body.get("ok") is True
        for it in body.get("items") or []:
            assert int(it["organization_id"]) == c["org_a_id"]
        assert "SKU_B_ONLY_ORG2" not in json.dumps(body)

    def test_get_movements_alerts_suppliers_po_payments_org_a(self, tenant_isolation_world):
        c = tenant_isolation_world
        client = TestClient(app)
        for path in (
            "/inventory/movements",
            "/inventory/alerts",
            "/inventory/suppliers",
            "/inventory/purchase-orders",
            "/inventory/supplier-payments",
        ):
            r = client.get(path, headers=_auth(c["token_a"]))
            assert r.status_code == 200, path
            assert_response_scoped_to_org(
                r, expected_org_id=c["org_a_id"], forbidden_org_id=c["org_b_id"]
            )

    def test_put_item_cross_tenant(self, tenant_isolation_world):
        c = tenant_isolation_world
        client = TestClient(app)
        r = client.put(
            f"/inventory/item/{c['item_b_id']}",
            headers=_auth(c["token_a"]),
            json={"sku_name": "pwned"},
        )
        assert_no_cross_tenant_success(r)

    def test_post_movement_cross_tenant_item(self, tenant_isolation_world):
        c = tenant_isolation_world
        client = TestClient(app)
        r = client.post(
            "/inventory/movement",
            headers=_auth(c["token_a"]),
            json={
                "inventory_item_id": c["item_b_id"],
                "quantity_delta": -1,
                "movement_type": "OUT",
            },
        )
        assert_no_cross_tenant_success(r)

    def test_post_po_cross_tenant_supplier(self, tenant_isolation_world):
        c = tenant_isolation_world
        client = TestClient(app)
        r = client.post(
            "/inventory/purchase-order",
            headers=_auth(c["token_a"]),
            json={
                "supplier_id": c["sup_b_id"],
                "order_date": "2026-02-01",
                "lines": [{"sku_name": "x", "quantity_ordered": 1, "unit_cost_pre_tax": 1}],
            },
        )
        assert_no_cross_tenant_success(r)

    def test_receive_line_cross_tenant_po(self, tenant_isolation_world):
        c = tenant_isolation_world
        client = TestClient(app)
        r = client.post(
            f"/inventory/purchase-order/{c['po_b_id']}/receive-line",
            headers=_auth(c["token_a"]),
            json={
                "line_id": c["line_b_id"],
                "quantity": 1,
                "inventory_location": "dock",
            },
        )
        assert_no_cross_tenant_success(r)

    def test_patch_po_invoice_cross_tenant(self, tenant_isolation_world):
        c = tenant_isolation_world
        client = TestClient(app)
        r = client.patch(
            f"/inventory/purchase-order/{c['po_b_id']}/supplier-invoice",
            headers=_auth(c["token_a"]),
            json={"supplier_invoice_no": "INV-999"},
        )
        assert_no_cross_tenant_success(r)

    def test_supplier_payment_cross_tenant(self, tenant_isolation_world):
        c = tenant_isolation_world
        client = TestClient(app)
        r = client.post(
            "/inventory/supplier-payment",
            headers=_auth(c["token_a"]),
            json={
                "supplier_id": c["sup_b_id"],
                "amount_inr": 100,
            },
        )
        assert_no_cross_tenant_success(r)

    def test_post_item_create_stays_in_org_a(self, tenant_isolation_world):
        c = tenant_isolation_world
        client = TestClient(app)
        r = client.post(
            "/inventory/item",
            headers=_auth(c["token_a"]),
            json={"sku_name": "NEW_A_SKU", "quantity": 1, "location": "wh"},
        )
        assert r.status_code == 200
        body = r.json()
        assert int(body["item"]["organization_id"]) == c["org_a_id"]

    def test_post_inventory_add_org_scoped(self, tenant_isolation_world):
        c = tenant_isolation_world
        client = TestClient(app)
        r = client.post(
            "/inventory/add",
            headers=_auth(c["token_a"]),
            json={"sku_name": "ADD_A", "quantity": 3, "location": ""},
        )
        assert r.status_code == 200
        assert int(r.json()["organization_id"]) == c["org_a_id"]


class TestAuditAndControlPlaneIsolation:
    def test_post_audit_visible_only_to_same_tenant(self, tenant_isolation_world):
        c = tenant_isolation_world
        client = TestClient(app)
        marker = "AUDIT_MARKER_ORG_A_ONLY"
        r = client.post(
            "/audit",
            headers=_auth(c["token_a"]),
            json={
                "action_type": "test_action",
                "entity": marker,
                "entity_id": "1",
                "source": "USER",
                "result": "SUCCESS",
                "metadata": {"k": 1},
            },
        )
        assert r.status_code == 200
        rb = client.get("/audit", headers=_auth(c["token_b"]))
        assert rb.status_code == 200
        assert marker not in json.dumps(rb.json())

    def test_audit_list_no_org_b_rows(self, tenant_isolation_world):
        c = tenant_isolation_world
        client = TestClient(app)
        r = client.get("/audit", headers=_auth(c["token_a"]))
        assert r.status_code == 200
        body = r.json()
        assert "SECRET_B_ACTION" not in json.dumps(body)
        for row in body.get("items") or []:
            assert int(row["org_id"]) == c["org_a_id"]

    def test_control_plane_alerts_jobs_isolated(self, tenant_isolation_world):
        c = tenant_isolation_world
        client = TestClient(app)
        ra = client.get("/alerts", headers=_auth(c["token_a"]))
        assert ra.status_code == 200
        assert "ORG_B_CP_ALERT_SECRET" not in ra.text

        rj = client.get("/jobs", headers=_auth(c["token_a"]))
        assert rj.status_code == 200
        assert "ORG_B_JOB_SECRET" not in rj.text

    def test_post_job_org_isolated_in_listings(self, tenant_isolation_world):
        c = tenant_isolation_world
        client = TestClient(app)
        jtype = "tenant_isolation_job_type_a"
        pr = client.post(
            "/jobs",
            headers=_auth(c["token_a"]),
            json={"type": jtype, "payload": {"x": 1}},
        )
        assert pr.status_code == 200
        rb = client.get("/jobs", headers=_auth(c["token_b"]))
        assert rb.status_code == 200
        types_b = {it.get("type") for it in (rb.json().get("items") or [])}
        assert jtype not in types_b

    def test_control_plane_reorder_creates_in_active_org_only(self, tenant_isolation_world):
        c = tenant_isolation_world
        client = TestClient(app)
        r = client.post(
            "/inventory/reorder",
            headers=_auth(c["token_a"]),
            json={"item_name": "reorder-test", "quantity": 2},
        )
        assert r.status_code == 200
        with c["factory"]() as s:
            rows = s.execute(
                select(ControlPlaneAlert).where(ControlPlaneAlert.message.like("%reorder-test%"))
            ).scalars().all()
            assert len(rows) >= 1
            assert all(int(x.organization_id) == c["org_a_id"] for x in rows)


class TestTenancySwitchAndHeaders:
    def test_switch_to_foreign_org_forbidden(self, tenant_isolation_world):
        c = tenant_isolation_world
        client = TestClient(app)
        r = client.post(
            f"/me/switch-organization/{c['org_b_id']}",
            headers=_auth(c["token_a"]),
        )
        assert r.status_code == 403

    def test_me_organizations_never_lists_foreign_membership(self, tenant_isolation_world):
        c = tenant_isolation_world
        client = TestClient(app)
        r = client.get("/me/organizations", headers=_auth(c["token_a"]))
        assert r.status_code == 200
        org_ids = {m["organization"]["id"] for m in r.json()}
        assert c["org_b_id"] not in org_ids

    def test_client_org_headers_do_not_override_jwt_tenant(self, tenant_isolation_world):
        c = tenant_isolation_world
        client = TestClient(app)
        r = client.get(
            "/inventory",
            headers={
                **_auth(c["token_a"]),
                "X-Org-ID": str(c["org_b_id"]),
                "X-THIRAMAI-DEV-ORG-ID": str(c["org_b_id"]),
            },
        )
        assert r.status_code == 200
        body = r.json()
        for it in body.get("items") or []:
            assert int(it["organization_id"]) == c["org_a_id"]
        assert "SKU_B_ONLY_ORG2" not in json.dumps(body)


class TestSequentialIdorInventoryItem:
    def test_put_sequential_ids_never_returns_org_b_item(self, tenant_isolation_world):
        c = tenant_isolation_world
        client = TestClient(app)
        for i in range(1, max(c["item_a_id"], c["item_b_id"]) + 5):
            resp = client.put(
                f"/inventory/item/{i}",
                headers=_auth(c["token_a"]),
                json={"sku_name": "probe"},
            )
            if resp.status_code == 200:
                body = resp.json()
                item = body.get("item") or {}
                assert int(item.get("organization_id", -1)) == c["org_a_id"]


class TestAnalyticsSummaryIsolation:
    def test_analytics_summary_org_marker(self, tenant_isolation_world):
        c = tenant_isolation_world
        client = TestClient(app)
        r = client.get("/analytics/summary", headers=_auth(c["token_a"]))
        assert r.status_code == 200
        body = r.json()
        assert int(body["organization_id"]) == c["org_a_id"]
        _walk_assert_no_forbidden_org(body, c["org_b_id"])


class TestAuthDisabledDevOrgHeaderDoesNotOverrideBearer:
    def test_bearer_wins_over_dev_org_header(self, tenant_isolation_world, monkeypatch: pytest.MonkeyPatch):
        c = tenant_isolation_world
        monkeypatch.setenv("THIRAMAI_AUTH_DISABLED", "1")
        client = TestClient(app)
        r = client.get(
            "/inventory",
            headers={
                **_auth(c["token_a"]),
                "X-THIRAMAI-DEV-ORG-ID": str(c["org_b_id"]),
            },
        )
        assert r.status_code == 200
        for it in r.json().get("items") or []:
            assert int(it["organization_id"]) == c["org_a_id"]
