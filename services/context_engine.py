"""
Phase 3 — business reality snapshot for the AI decision engine.

Aggregates inventory alerts, billing exposure, and production signals into one JSON-safe dict.
Distinct from ``core.context_engine`` (vault / council packs).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import Asset, Invoice, ProductionLog
from services import inventory_phase2_service as inv2
from services import production_phase2_service as prod2


def _dec(x: Any) -> Decimal:
    if x is None:
        return Decimal("0")
    return Decimal(str(x))


def build_business_context_snapshot(organization_id: int) -> dict[str, Any]:
    """
    Return structured tenant context for decision prompts.

    Keys:
      - inventory_alerts, inventory_summary
      - financial_summary (unpaid / overdue-style signals)
      - production_status (totals, machines, waste hint)
    """
    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "invalid organization_id"}

    snapshot: dict[str, Any] = {
        "ok": True,
        "organization_id": oid,
        "as_of_date": date.today().isoformat(),
        "inventory_alerts": [],
        "inventory_summary": {},
        "financial_summary": {},
        "production_status": {},
    }

    # --- Inventory (Phase 2) ---
    try:
        low = inv2.list_low_stock_alerts_sync(organization_id=oid)
        if low.get("ok"):
            snapshot["inventory_alerts"] = low.get("alerts") or []
        lst = inv2.list_inventory_items_sync(organization_id=oid)
        if lst.get("ok"):
            items = lst.get("items") or []
            total_skus = len(items)
            total_qty = sum(float(x.get("quantity") or 0) for x in items)
            snapshot["inventory_summary"] = {
                "sku_rows": total_skus,
                "total_quantity_on_hand": round(total_qty, 4),
            }
    except Exception as exc:
        snapshot["inventory_summary"] = {"error": type(exc).__name__}

    # --- Billing: unpaid / partial invoices (ORM) ---
    factory = get_session_factory()
    if factory is not None:
        try:
            with factory() as session:
                unpaid = list(
                    session.scalars(
                        select(Invoice).where(
                            Invoice.organization_id == oid,
                            Invoice.payment_status.in_(("unpaid", "partial")),
                        )
                    ).all()
                )
                due_total = sum(_dec(x.grand_total_inr) for x in unpaid)
                # Simple “overdue” proxy: invoice_date before today and still unpaid
                today = date.today()
                overdue_ids: list[int] = []
                overdue_amt = Decimal("0")
                for inv in unpaid:
                    if inv.invoice_date is not None and inv.invoice_date < today:
                        overdue_ids.append(int(inv.id))
                        overdue_amt += _dec(inv.grand_total_inr)
                snapshot["financial_summary"] = {
                    "unpaid_invoice_count": len(unpaid),
                    "unpaid_total_inr": float(due_total.quantize(Decimal("0.01"))),
                    "overdue_invoice_ids": overdue_ids[:50],
                    "overdue_total_inr": float(overdue_amt.quantize(Decimal("0.01"))),
                }
        except Exception as exc:
            snapshot["financial_summary"] = {"error": type(exc).__name__}

        # --- Production: summary + machines + waste hint ---
        try:
            ps = prod2.production_summary_sync(organization_id=oid)
            if ps.get("ok"):
                snapshot["production_status"]["rolling_totals"] = {
                    "log_count": ps.get("log_count"),
                    "total_yield_out": ps.get("total_yield_out"),
                    "total_blocks_out": ps.get("total_blocks_out"),
                    "total_labor_cost_inr": ps.get("total_labor_cost_inr"),
                }
            ms = prod2.list_machines_sync(organization_id=oid)
            if ms.get("ok"):
                machines = ms.get("machines") or []
                down = sum(1 for m in machines if str(m.get("status", "")).lower() in ("down", "maintenance", "stopped"))
                snapshot["production_status"]["machines"] = {
                    "count": len(machines),
                    "down_or_maintenance_count": down,
                    "details": machines[:30],
                }
            waste = _estimate_waste_percent(organization_id=oid, factory=factory)
            if waste is not None:
                snapshot["production_status"]["waste_percent_estimate"] = waste
        except Exception as exc:
            snapshot["production_status"]["error"] = type(exc).__name__

    return snapshot


def _estimate_waste_percent(
    *,
    organization_id: int,
    factory: Any,
) -> float | None:
    """
    Heuristic: 100 * (1 - yield / raw_in) averaged over recent logs for this org (via Asset).
    Returns None if insufficient data.
    """
    oid = int(organization_id)
    if factory is None:
        return None
    with factory() as s:
        stmt = (
            select(ProductionLog, Asset)
            .join(Asset, Asset.id == ProductionLog.asset_id)
            .where(Asset.organization_id == oid)
            .order_by(ProductionLog.id.desc())
            .limit(50)
        )
        logs = list(s.execute(stmt).all())
    ratios: list[float] = []
    for row in logs:
        pl = row[0]
        if not isinstance(pl, ProductionLog):
            continue
        raw_in = pl.raw_material_in
        yld = pl.yield_out
        if raw_in is None or yld is None:
            continue
        ri = float(raw_in)
        yo = float(yld)
        if ri <= 0:
            continue
        # “Waste” as input not converted to labelled yield (rough proxy)
        waste_pct = max(0.0, min(100.0, 100.0 * (1.0 - yo / ri)))
        ratios.append(waste_pct)
    if not ratios:
        return None
    return round(sum(ratios) / len(ratios), 2)
