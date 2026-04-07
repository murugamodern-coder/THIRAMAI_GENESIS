"""
Unit economics: COGS from inventory unit cost vs bill lines, net profit rollup (Phase 4 + Phase 6).

Revenue uses bill ``total_amount`` (tax-inclusive), consistent with ``analytics_service``.
COGS uses ``inventory.unit_cost_pre_tax × quantity`` per line (pre-tax cost basis) — a deliberate
approximation when mixing with tax-inclusive revenue; interpret net profit as operational signal, not GAAP.

**Maintenance:** completed repairs (``maintenance_logs.fixed_at`` in-period, ``cost``) reduce net profit.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from core.database import get_session_factory
from core.db.models import Bill, Equipment, Inventory, MaintenanceLog, OperationalExpense, Organization, StaffProfile
from core.db.provisioning import ensure_tenant_defaults, sync_organizations_id_sequence
from services.dashboard_ops_state import get_operational_infra_budget_inr_override

_identity_lock = threading.Lock()
# In-process overlay after DB writes (autoscale / SRE can read without hitting DB every call).
_org_identity_cache: dict[int, dict[str, Any]] = {}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _start_of_month_utc(now: datetime) -> datetime:
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc)


def _start_of_next_month_utc(now: datetime) -> datetime:
    if now.month == 12:
        return datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    return datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)


def _sum_revenue(
    session: Session,
    *,
    organization_id: int,
    start: datetime,
    end: datetime,
) -> Decimal:
    q = select(func.coalesce(func.sum(Bill.total_amount), 0)).where(
        Bill.organization_id == int(organization_id),
        Bill.created_at >= start,
        Bill.created_at < end,
    )
    v = session.execute(q).scalar_one()
    return Decimal(str(v or 0)).quantize(Decimal("0.01"))


def inventory_cost_map(session: Session, organization_id: int) -> dict[str, Decimal]:
    """SKU name → unit cost pre-tax (0 if unknown)."""
    rows = session.execute(
        select(Inventory).where(Inventory.organization_id == int(organization_id))
    ).scalars().all()
    out: dict[str, Decimal] = {}
    for r in rows:
        sku = (r.sku_name or "").strip()
        if not sku:
            continue
        c = r.unit_cost_pre_tax
        out[sku] = Decimal(str(c)).quantize(Decimal("0.01")) if c is not None else Decimal("0")
    return out


def compute_cogs_for_period(
    session: Session,
    *,
    organization_id: int,
    start: datetime,
    end: datetime,
) -> Decimal:
    """Σ (line quantity × unit_cost_pre_tax from current inventory snapshot)."""
    oid = int(organization_id)
    costs = inventory_cost_map(session, oid)
    stmt = select(Bill).where(
        Bill.organization_id == oid,
        Bill.created_at >= start,
        Bill.created_at < end,
    )
    total = Decimal("0")
    for bill in session.execute(stmt).scalars().all():
        for line in bill.items or []:
            if not isinstance(line, dict):
                continue
            sku = (line.get("sku_name") or "").strip()
            if not sku:
                continue
            try:
                qty = Decimal(str(line.get("quantity") or 0))
            except Exception:
                continue
            unit_cost = costs.get(sku, Decimal("0"))
            total += (qty * unit_cost).quantize(Decimal("0.01"))
    return total.quantize(Decimal("0.01"))


def sum_active_monthly_salaries(session: Session, *, organization_id: int) -> Decimal:
    q = select(func.coalesce(func.sum(StaffProfile.basic_salary), 0)).where(
        StaffProfile.organization_id == int(organization_id),
        StaffProfile.status == "active",
    )
    v = session.execute(q).scalar_one()
    return Decimal(str(v or 0)).quantize(Decimal("0.01"))


def sum_operational_expenses_period(
    session: Session,
    *,
    organization_id: int,
    start_date: date,
    end_date_exclusive: date,
) -> Decimal:
    q = select(func.coalesce(func.sum(OperationalExpense.amount_inr), 0)).where(
        OperationalExpense.organization_id == int(organization_id),
        OperationalExpense.expense_date >= start_date,
        OperationalExpense.expense_date < end_date_exclusive,
    )
    v = session.execute(q).scalar_one()
    return Decimal(str(v or 0)).quantize(Decimal("0.01"))


def sum_maintenance_costs_period(
    session: Session,
    *,
    organization_id: int,
    start: datetime,
    end: datetime,
) -> Decimal:
    """Sum repair **cost** for equipment in-org where **fixed_at** falls in ``[start, end)``."""
    oid = int(organization_id)
    q = (
        select(func.coalesce(func.sum(MaintenanceLog.cost), 0))
        .select_from(MaintenanceLog)
        .join(Equipment, Equipment.id == MaintenanceLog.equipment_id)
        .where(
            Equipment.organization_id == oid,
            MaintenanceLog.fixed_at.is_not(None),
            MaintenanceLog.fixed_at >= start,
            MaintenanceLog.fixed_at < end,
        )
    )
    v = session.execute(q).scalar_one()
    return Decimal(str(v or 0)).quantize(Decimal("0.01"))


def sku_cogs_breakdown(
    session: Session,
    *,
    organization_id: int,
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    """Per-SKU sold qty and extended COGS (for AI / dashboards)."""
    oid = int(organization_id)
    costs = inventory_cost_map(session, oid)
    qty_by_sku: dict[str, Decimal] = {}
    for bill in session.execute(
        select(Bill).where(
            Bill.organization_id == oid,
            Bill.created_at >= start,
            Bill.created_at < end,
        )
    ).scalars().all():
        for line in bill.items or []:
            if not isinstance(line, dict):
                continue
            sku = (line.get("sku_name") or "").strip()
            if not sku:
                continue
            try:
                q = Decimal(str(line.get("quantity") or 0))
            except Exception:
                continue
            qty_by_sku[sku] = qty_by_sku.get(sku, Decimal("0")) + q
    out: list[dict[str, Any]] = []
    for sku, qty in sorted(qty_by_sku.items(), key=lambda x: x[0]):
        uc = costs.get(sku, Decimal("0"))
        ext = (qty * uc).quantize(Decimal("0.01"))
        out.append(
            {
                "sku_name": sku,
                "quantity_sold": float(qty),
                "unit_cost_pre_tax": float(uc),
                "extended_cogs_inr": float(ext),
            }
        )
    return out


def get_business_margin(
    organization_id: int,
    *,
    _as_of: datetime | None = None,
    _session_factory: Optional[Callable[[], Session]] = None,
) -> dict[str, Any]:
    """
    Current calendar month (UTC): revenue, COGS, active staff salaries, operational expenses, net profit.

    Intended for AI council and ``business_snapshot_service``.
    """
    oid = int(organization_id)
    factory: sessionmaker[Session] | None = _session_factory or get_session_factory()  # type: ignore[assignment]
    if factory is None:
        return {
            "ok": False,
            "error": "DATABASE_URL is not configured",
            "organization_id": oid,
        }

    now = _as_of if _as_of is not None else _utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    m0 = _start_of_month_utc(now)
    m1 = _start_of_next_month_utc(now)
    d0 = m0.date()
    d1 = m1.date()

    with factory() as session:
        revenue = _sum_revenue(session, organization_id=oid, start=m0, end=now + timedelta(microseconds=1))
        cogs = compute_cogs_for_period(session, organization_id=oid, start=m0, end=now + timedelta(microseconds=1))
        salaries = sum_active_monthly_salaries(session, organization_id=oid)
        opex = sum_operational_expenses_period(session, organization_id=oid, start_date=d0, end_date_exclusive=d1)
        maint = sum_maintenance_costs_period(
            session,
            organization_id=oid,
            start=m0,
            end=now + timedelta(microseconds=1),
        )
        net = revenue - cogs - salaries - opex - maint
        net = net.quantize(Decimal("0.01"))
        gross_margin_pct: float | None
        if revenue > 0:
            gross_margin_pct = float(((revenue - cogs) / revenue * Decimal("100")).quantize(Decimal("0.01")))
        else:
            gross_margin_pct = None

    return {
        "ok": True,
        "organization_id": oid,
        "period_utc": {"start": m0.isoformat(), "end_inclusive": now.isoformat()},
        "revenue_inr": str(revenue),
        "cogs_inr": str(cogs),
        "staff_salaries_monthly_inr": str(salaries),
        "operational_expenses_inr": str(opex),
        "maintenance_costs_inr": str(maint),
        "net_profit_inr": str(net),
        "gross_margin_pct": gross_margin_pct,
        "note": (
            "Revenue is tax-inclusive from bills; COGS uses pre-tax unit costs; maintenance costs "
            "(fixed_at in-period) deducted — management KPI, not GAAP."
        ),
    }


def infra_scaling_budget_check(
    organization_id: int,
    *,
    current_worker_nodes: int,
) -> dict[str, Any]:
    """
    Gate **predictive / reactive worker autoscale** against the operator-defined monthly infra cap.

    Uses unit economics context (``get_business_margin``) when configured so scaling does not ignore
    profitability signals.

    Env (user-defined operational budget):

    * ``THIRAMAI_OPERATIONAL_INFRA_BUDGET_INR`` — monthly INR cap for estimated worker infra.
      If unset, no budget gate is applied (scale allowed); persisted ``var/`` override is ignored
      until this env var is set. When set, optional operator file override replaces the cap value.
    * ``THIRAMAI_WORKER_MONTHLY_COST_INR_EST`` — estimated all-in cost per running worker / month (default 500).
    * ``THIRAMAI_AUTOSCALE_REQUIRE_POSITIVE_MARGIN`` — when ``1``/``true``, block scale-up if
      current-month ``net_profit_inr`` is negative (requires valid ``organization_id`` + DB).
    """
    oid = int(organization_id)
    # Read env on every call (no module-level cache). Persisted file override only applies when
    # THIRAMAI_OPERATIONAL_INFRA_BUDGET_INR is set — otherwise the gate is off (tests / operators
    # rely on env to enable the cap; var/ override adjusts the cap value when both exist).
    env_budget_raw = (os.getenv("THIRAMAI_OPERATIONAL_INFRA_BUDGET_INR") or "").strip()
    per_raw = (os.getenv("THIRAMAI_WORKER_MONTHLY_COST_INR_EST") or "500").strip() or "500"
    try:
        per_node = Decimal(per_raw).quantize(Decimal("0.01"))
    except Exception:
        per_node = Decimal("500.00")

    nodes = max(0, int(current_worker_nodes))

    base: dict[str, Any] = {
        "ok": True,
        "organization_id": oid,
        "current_worker_nodes": nodes,
        "worker_monthly_cost_inr_est": str(per_node),
    }

    if not env_budget_raw:
        base["budget_configured"] = False
        base["allow_scale_up"] = True
        base["reason"] = "THIRAMAI_OPERATIONAL_INFRA_BUDGET_INR unset — no monthly infra cap"
        return base

    file_raw = (get_operational_infra_budget_inr_override() or "").strip()
    cap_raw = file_raw if file_raw else env_budget_raw

    try:
        cap = Decimal(cap_raw).quantize(Decimal("0.01"))
    except Exception:
        return {
            **base,
            "budget_configured": True,
            "allow_scale_up": False,
            "reason": "invalid THIRAMAI_OPERATIONAL_INFRA_BUDGET_INR",
        }

    current_spend = (per_node * nodes).quantize(Decimal("0.01"))
    projected = (per_node * (nodes + 1)).quantize(Decimal("0.01"))

    budget_block = projected > cap

    margin_check: dict[str, Any] | None = None
    margin_block = False
    soft = (os.getenv("THIRAMAI_AUTOSCALE_REQUIRE_POSITIVE_MARGIN") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if soft and oid > 0:
        margin = get_business_margin(oid)
        margin_check = {"ok": margin.get("ok"), "net_profit_inr": margin.get("net_profit_inr")}
        if margin.get("ok") and Decimal(str(margin.get("net_profit_inr") or "0")) < 0:
            margin_block = True

    if budget_block:
        allow = False
        reason = "Adding a worker would exceed THIRAMAI_OPERATIONAL_INFRA_BUDGET_INR (operational budget)"
    elif margin_block:
        allow = False
        reason = (
            "THIRAMAI_AUTOSCALE_REQUIRE_POSITIVE_MARGIN: net profit negative this month — scale-up blocked"
        )
    else:
        allow = True
        reason = ""

    out: dict[str, Any] = {
        **base,
        "budget_configured": True,
        "budget_cap_inr": str(cap),
        "estimated_current_infra_inr": str(current_spend),
        "projected_after_one_more_inr": str(projected),
        "allow_scale_up": allow,
        "reason": reason,
    }
    if margin_check is not None:
        out["margin_check"] = margin_check
    return out


def infra_scaling_budget_remaining(
    organization_id: int,
    *,
    current_worker_nodes: int,
) -> dict[str, Any]:
    """
    Same as ``infra_scaling_budget_check`` plus ``remaining_infra_budget_inr`` (cap − estimated spend).

    Used by SRE / dashboards; amounts are monthly INR estimates from env caps.
    """
    snap = infra_scaling_budget_check(organization_id, current_worker_nodes=current_worker_nodes)
    if not snap.get("budget_configured"):
        return {**snap, "remaining_infra_budget_inr": None}
    cap = Decimal(str(snap["budget_cap_inr"]))
    spent = Decimal(str(snap["estimated_current_infra_inr"]))
    rem = (cap - spent).quantize(Decimal("0.01"))
    if rem < 0:
        rem = Decimal("0.00")
    out = {**snap, "remaining_infra_budget_inr": str(rem)}
    ci = get_corporate_economics_context(int(organization_id))
    if ci.get("company_name") or ci.get("gst_number"):
        out["corporate_identity"] = ci
    return out


def load_corporate_identity_from_db(organization_id: int) -> dict[str, Any]:
    """Read ``organizations.name`` / ``gst_number`` for economics + dashboard context."""
    oid = int(organization_id)
    factory = get_session_factory()
    if factory is None:
        return {"company_name": "", "gst_number": None, "organization_id": oid}
    try:
        with factory() as session:
            org = session.get(Organization, oid)
            if org is None:
                return {"company_name": "", "gst_number": None, "organization_id": oid}
            gst = (org.gst_number or "").strip() or None
            return {
                "organization_id": oid,
                "company_name": (org.name or "").strip(),
                "gst_number": gst,
            }
    except Exception:
        return {"company_name": "", "gst_number": None, "organization_id": oid}


def get_corporate_economics_context(organization_id: int) -> dict[str, Any]:
    """
    Corporate legal identity for UI and infra budget payloads.

    Uses the in-memory cache when warmed; otherwise loads from the database once and caches.
    """
    oid = int(organization_id)
    with _identity_lock:
        hit = _org_identity_cache.get(oid)
    if hit is not None:
        return dict(hit)
    row = load_corporate_identity_from_db(oid)
    with _identity_lock:
        _org_identity_cache[oid] = dict(row)
    return dict(row)


def persist_corporate_identity(
    organization_id: int,
    *,
    company_name: str,
    gst_number: str,
) -> dict[str, Any]:
    """
    Persist company display name + GST on ``organizations`` and refresh the economics in-process cache.
    """
    oid = int(organization_id)
    name = (company_name or "").strip()
    if not name:
        raise ValueError("company_name_required")
    gst = (gst_number or "").strip() or None
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("database_not_configured")
    with factory() as session:
        org = session.get(Organization, oid)
        if org is None:
            org = Organization(id=oid, name=name, plan="free", gst_number=gst)
            session.add(org)
            session.flush()
            ensure_tenant_defaults(session, oid)
            try:
                sync_organizations_id_sequence(session)
            except Exception:
                pass
        else:
            org.name = name
            org.gst_number = gst
        session.commit()
        out: dict[str, Any] = {
            "organization_id": oid,
            "company_name": org.name,
            "gst_number": org.gst_number,
        }
    with _identity_lock:
        _org_identity_cache[oid] = dict(out)
    return out
