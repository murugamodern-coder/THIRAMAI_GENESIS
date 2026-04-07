"""
Revenue analysis for operator guidance — **read-only**, **not** financial execution.

Uses existing dashboard aggregates and an optional same-day **gross margin proxy**
(revenue from ``bills`` minus inventory ``unit_price`` × quantity sold on those lines).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import Bill, Inventory
from core.observability import log_structured


def _parse_inr(s: Any) -> Decimal:
    try:
        return Decimal(str(s).replace(",", "").strip() or "0").quantize(Decimal("0.01"))
    except Exception:
        return Decimal("0.00")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _start_of_today_utc(now: datetime) -> datetime:
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def _profit_proxy_today(organization_id: int) -> dict[str, Any]:
    """
    Indicative gross margin using current inventory unit_price as cost proxy for lines sold today.
    """
    oid = int(organization_id)
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "reason": "database_not_configured"}

    now = _utc_now()
    start = _start_of_today_utc(now)
    end = start + timedelta(days=1)

    try:
        with factory() as session:
            stmt_b = (
                select(Bill)
                .where(
                    Bill.organization_id == oid,
                    Bill.created_at >= start,
                    Bill.created_at < end,
                )
                .order_by(Bill.created_at.asc())
            )
            bills = list(session.execute(stmt_b).scalars().all())

            stmt_i = select(Inventory).where(Inventory.organization_id == oid)
            inv_rows = list(session.execute(stmt_i).scalars().all())
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}

    price_by_sku: dict[str, Decimal] = {}
    for r in inv_rows:
        sku = (r.sku_name or "").strip().lower()
        if sku and r.unit_price is not None:
            try:
                price_by_sku[sku] = Decimal(str(r.unit_price)).quantize(Decimal("0.0001"))
            except Exception:
                continue

    revenue = Decimal("0.00")
    cogs_proxy = Decimal("0.00")
    for b in bills:
        revenue += Decimal(str(b.total_amount or 0)).quantize(Decimal("0.01"))
        items = b.items if isinstance(b.items, list) else []
        for line in items:
            if not isinstance(line, dict):
                continue
            sku = (line.get("sku_name") or "").strip().lower()
            try:
                qty = Decimal(str(line.get("quantity") or 0))
            except Exception:
                qty = Decimal("0")
            uc = price_by_sku.get(sku)
            if uc is not None and qty > 0:
                cogs_proxy += (uc * qty).quantize(Decimal("0.01"))

    margin = (revenue - cogs_proxy).quantize(Decimal("0.01"))
    return {
        "ok": True,
        "bills_count_today": len(bills),
        "revenue_inr": float(revenue),
        "cogs_proxy_inr": float(cogs_proxy),
        "estimated_gross_margin_inr": float(margin),
        "method": "bills_total_minus_inventory_unit_price_times_qty_sold_today",
    }


def analyze_revenue(context: dict[str, Any]) -> dict[str, Any]:
    """
    Build a revenue snapshot + trend label + profit proxy + non-executing alerts.

    Uses ``context['_tenant_state']`` when present (``dashboard`` block); otherwise reads org from context.
    """
    state = context.get("_tenant_state") if isinstance(context.get("_tenant_state"), dict) else {}
    oid = int(state.get("organization_id") or context.get("organization_id") or 0)
    request_id = context.get("request_id")

    if oid <= 0:
        out = {
            "ok": False,
            "organization_id": oid,
            "today_revenue_inr": None,
            "weekly_trend": "unknown",
            "profit_estimate": None,
            "alerts": [{"level": "warning", "message": "organization_id required for revenue analysis"}],
        }
        log_structured("revenue_engine.analyze", request_id=request_id, organization_id=oid, ok=False)
        return out

    dash = state.get("dashboard") if isinstance(state.get("dashboard"), dict) else {}
    if not dash.get("ok"):
        err = dash.get("error") or "dashboard_unavailable"
        out = {
            "ok": False,
            "organization_id": oid,
            "today_revenue_inr": None,
            "weekly_trend": "unknown",
            "profit_estimate": None,
            "alerts": [{"level": "warning", "message": str(err)}],
        }
        log_structured(
            "revenue_engine.analyze",
            request_id=request_id,
            organization_id=oid,
            ok=False,
            error=str(err)[:120],
        )
        return out

    rev = dash.get("revenue_inr") or {}
    today_s = str(rev.get("today") or "0")
    week_s = str(rev.get("this_week") or "0")
    month_s = str(rev.get("this_month") or "0")
    today = _parse_inr(today_s)
    week = _parse_inr(week_s)
    month = _parse_inr(month_s)

    now = _utc_now()
    sod = _start_of_today_utc(now)
    week_start = sod - timedelta(days=sod.weekday())
    elapsed_week_days = max(1, min(int((now - week_start).total_seconds() // 86400) + 1, 7))
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    days_in_month = max(int((now - month_start).total_seconds() // 86400) + 1, 1)

    expected_week_from_month = (month / Decimal(days_in_month)) * Decimal(7) if month > 0 else Decimal(0)
    weekly_trend = "insufficient_history"
    if expected_week_from_month > 0 and elapsed_week_days >= 1:
        ratio = float(week / expected_week_from_month)
        if ratio > 1.2:
            weekly_trend = "strong_vs_monthly_run_rate"
        elif ratio < 0.75:
            weekly_trend = "soft_vs_monthly_run_rate"
        else:
            weekly_trend = "in_line_with_monthly_run_rate"

    profit = _profit_proxy_today(oid)
    profit_estimate: dict[str, Any] | None = None
    if profit.get("ok"):
        profit_estimate = {
            "disclaimer": "indicative_only_not_audited_financial_advice",
            "estimated_gross_margin_inr_today": profit.get("estimated_gross_margin_inr"),
            "revenue_inr_today_from_bills": profit.get("revenue_inr"),
            "cogs_proxy_inr": profit.get("cogs_proxy_inr"),
            "bills_count_today": profit.get("bills_count_today"),
            "method": profit.get("method"),
        }
    else:
        profit_estimate = {
            "disclaimer": "margin_proxy_unavailable",
            "detail": profit.get("reason", "unknown"),
        }

    alerts: list[dict[str, Any]] = []
    if today == 0 and month > 0:
        alerts.append(
            {
                "level": "info",
                "code": "no_revenue_today",
                "message": "No billed revenue today while prior month activity exists — review channels or POS.",
            }
        )
    if profit.get("ok") and profit.get("estimated_gross_margin_inr") is not None:
        mg = float(profit["estimated_gross_margin_inr"])
        if mg < 0:
            alerts.append(
                {
                    "level": "warning",
                    "code": "negative_gross_proxy_today",
                    "message": "Estimated gross margin proxy is negative — validate inventory unit costs vs sell prices.",
                }
            )

    out = {
        "ok": True,
        "organization_id": oid,
        "today_revenue_inr": today_s,
        "weekly_revenue_inr": week_s,
        "monthly_revenue_inr": month_s,
        "weekly_trend": weekly_trend,
        "profit_estimate": profit_estimate,
        "alerts": alerts,
        "as_of_utc": dash.get("as_of_utc"),
    }
    log_structured(
        "revenue_engine.analyze",
        request_id=request_id,
        organization_id=oid,
        ok=True,
        weekly_trend=weekly_trend,
        alerts=len(alerts),
    )
    return out
