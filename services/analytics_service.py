"""
Business dashboard metrics from ``bills`` and ``inventory`` (Phase 5).

All public entrypoints are **synchronous** — call from FastAPI via ``asyncio.to_thread`` so the
event loop stays responsive. The brain (orchestrator) may call the same functions directly.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from core.database import get_session_factory
from core.db.models import Bill, Inventory


def _money_str(d: Decimal) -> str:
    return str(d.quantize(Decimal("0.01")))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _start_of_today_utc(now: datetime) -> datetime:
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def _start_of_iso_week_utc(now: datetime) -> datetime:
    """Monday 00:00 UTC of the calendar week containing ``now``."""
    sod = _start_of_today_utc(now)
    return sod - timedelta(days=sod.weekday())


def _start_of_month_utc(now: datetime) -> datetime:
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc)


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


def _gst_from_items(lines: list[Any]) -> tuple[Decimal, Decimal, Decimal]:
    cgst = sgst = igst = Decimal("0")
    if not isinstance(lines, list):
        return cgst, sgst, igst
    for line in lines:
        if not isinstance(line, dict):
            continue
        cgst += Decimal(str(line.get("cgst") or 0))
        sgst += Decimal(str(line.get("sgst") or 0))
        igst += Decimal(str(line.get("igst") or 0))
    return cgst.quantize(Decimal("0.01")), sgst.quantize(Decimal("0.01")), igst.quantize(Decimal("0.01"))


def _aggregate_gst_for_range(
    session: Session,
    *,
    organization_id: int,
    start: datetime,
    end: datetime,
) -> dict[str, str]:
    stmt = select(Bill.items).where(
        Bill.organization_id == int(organization_id),
        Bill.created_at >= start,
        Bill.created_at < end,
    )
    rows = session.execute(stmt).scalars().all()
    tc = ts = ti = Decimal("0")
    for blob in rows:
        c, s, i = _gst_from_items(blob if isinstance(blob, list) else [])
        tc += c
        ts += s
        ti += i
    return {
        "cgst": _money_str(tc),
        "sgst": _money_str(ts),
        "igst": _money_str(ti),
    }


def _top_skus_from_bills(
    session: Session,
    *,
    organization_id: int,
    limit: int = 5,
) -> list[dict[str, Any]]:
    stmt = select(Bill.items).where(Bill.organization_id == int(organization_id))
    rows = session.execute(stmt).scalars().all()
    qty_by_sku: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for blob in rows:
        if not isinstance(blob, list):
            continue
        for line in blob:
            if not isinstance(line, dict):
                continue
            sku = (line.get("sku_name") or "").strip()
            if not sku:
                continue
            try:
                q = Decimal(str(line.get("quantity") or 0))
            except Exception:
                continue
            qty_by_sku[sku] += q
    ranked = sorted(qty_by_sku.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [{"sku_name": k, "quantity_sold": float(v.quantize(Decimal("0.0001")))} for k, v in ranked]


def compute_dashboard_summary_sync(
    organization_id: int,
    *,
    low_stock_threshold: int = 5,
    _session_factory: Optional[Callable[[], Session]] = None,
    _as_of: datetime | None = None,
) -> dict[str, Any]:
    """
    Revenue (today / this week / this month), GST breakdowns, top 5 SKUs by quantity (all-time bills).

    ``low_stock_threshold`` is echoed for clients; low-stock rows are **not** included here
    (use ``list_low_stock_alerts_sync``).
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
    start_today = _start_of_today_utc(now)
    end_today = start_today + timedelta(days=1)
    start_week = _start_of_iso_week_utc(now)
    start_month = _start_of_month_utc(now)
    end_all = now + timedelta(microseconds=1)

    with factory() as session:
        rev_today = _sum_revenue(session, organization_id=oid, start=start_today, end=end_today)
        rev_week = _sum_revenue(session, organization_id=oid, start=start_week, end=end_all)
        rev_month = _sum_revenue(session, organization_id=oid, start=start_month, end=end_all)

        gst_today = _aggregate_gst_for_range(session, organization_id=oid, start=start_today, end=end_today)
        gst_week = _aggregate_gst_for_range(session, organization_id=oid, start=start_week, end=end_all)
        gst_month = _aggregate_gst_for_range(session, organization_id=oid, start=start_month, end=end_all)

        top = _top_skus_from_bills(session, organization_id=oid, limit=5)

    return {
        "ok": True,
        "organization_id": oid,
        "as_of_utc": now.isoformat(),
        "low_stock_threshold": int(low_stock_threshold),
        "revenue_inr": {
            "today": _money_str(rev_today),
            "this_week": _money_str(rev_week),
            "this_month": _money_str(rev_month),
        },
        "gst_collected_inr": {
            "today": gst_today,
            "this_week": gst_week,
            "this_month": gst_month,
        },
        "top_selling_products": top,
    }


def list_low_stock_alerts_sync(
    organization_id: int,
    *,
    threshold: int = 5,
    limit: int = 200,
    _session_factory: Optional[Callable[[], Session]] = None,
) -> dict[str, Any]:
    """Inventory rows for org with quantity strictly below ``threshold``."""
    oid = int(organization_id)
    thr = Decimal(str(int(threshold)))
    factory: sessionmaker[Session] | None = _session_factory or get_session_factory()  # type: ignore[assignment]
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured", "items": [], "threshold": int(threshold)}

    with factory() as session:
        stmt = (
            select(Inventory)
            .where(
                Inventory.organization_id == oid,
                Inventory.quantity < thr,
            )
            .order_by(Inventory.quantity.asc(), Inventory.sku_name.asc())
            .limit(limit)
        )
        rows = session.execute(stmt).scalars().all()
        items = [
            {
                "sku_name": r.sku_name,
                "quantity": float(r.quantity or Decimal("0")),
                "location": r.location or "",
                "unit_price_pre_tax": float(r.unit_price) if r.unit_price is not None else None,
                "gst_rate_percent": float(r.gst_rate_percent)
                if r.gst_rate_percent is not None
                else None,
                "hsn_code": (r.hsn_code or "").strip() or None,
            }
            for r in rows
        ]

    return {
        "ok": True,
        "organization_id": oid,
        "threshold": int(threshold),
        "count": len(items),
        "items": items,
    }


def user_requests_sales_analytics(message: str) -> bool:
    """Heuristic: user wants a POS / bills-based sales snapshot."""
    t = (message or "").strip().lower()
    if not t:
        return False
    if "sales report" in t or "selling report" in t or "sell report" in t:
        return True
    if "revenue" in t and ("today" in t or "week" in t or "month" in t):
        return True
    if "gst" in t and ("summary" in t or "collected" in t or "total" in t):
        return True
    if "how much" in t and "sell" in t:
        return True
    if "how much" in t and "sold" in t:
        return True
    return False


def format_sales_analytics_markdown(
    organization_id: int,
    *,
    low_stock_threshold: int = 5,
    _session_factory: Optional[Callable[[], Session]] = None,
    _as_of: datetime | None = None,
) -> str:
    """Compact Markdown block for council / chat (org-scoped)."""
    summary = compute_dashboard_summary_sync(
        organization_id,
        low_stock_threshold=low_stock_threshold,
        _session_factory=_session_factory,
        _as_of=_as_of,
    )
    if not summary.get("ok"):
        return (
            "**Sales analytics** could not be loaded. "
            + (summary.get("error") or "Check database configuration.")
        )

    alerts = list_low_stock_alerts_sync(
        organization_id,
        threshold=low_stock_threshold,
        _session_factory=_session_factory,
    )
    rev = summary["revenue_inr"]
    gst_m = summary["gst_collected_inr"]["this_month"]
    lines = [
        "### Sales snapshot (from bills)",
        "",
        f"- **Today (INR):** ₹{rev['today']}",
        f"- **This week (INR):** ₹{rev['this_week']}",
        f"- **This month (INR):** ₹{rev['this_month']}",
        "",
        "**GST collected (this month, INR)** — CGST ₹"
        + gst_m["cgst"]
        + " · SGST ₹"
        + gst_m["sgst"]
        + " · IGST ₹"
        + gst_m["igst"],
        "",
        "**Top SKUs (all-time quantity on bills)**",
    ]
    for row in summary.get("top_selling_products") or []:
        lines.append(f"- `{row['sku_name']}` — **{row['quantity_sold']}** units")
    if not summary.get("top_selling_products"):
        lines.append("- *(no bill line items yet)*")

    lines.extend(["", f"**Low stock (< {low_stock_threshold} units)**"])
    if alerts.get("ok") and alerts.get("items"):
        for it in alerts["items"][:10]:
            lines.append(f"- `{it['sku_name']}` @ {it['location'] or '—'} — **{it['quantity']}** left")
        if int(alerts.get("count") or 0) > 10:
            lines.append(f"- *…and {int(alerts['count']) - 10} more*")
    else:
        lines.append("- *(none below threshold)*")

    lines.append("")
    lines.append(f"_As of UTC: {summary.get('as_of_utc', '')}_")
    return "\n".join(lines)


def compute_financial_control_tower_sync(
    organization_id: int,
    *,
    days: int = 14,
    _session_factory: Optional[Callable[[], Session]] = None,
) -> dict[str, Any]:
    """
    Time-series for Executive cockpit charts: daily revenue, modeled opex, synthetic solar ROI % curve.

    Expenses are **estimated** as 32% of same-day revenue when no ledger detail exists (tunable display).
    Solar ROI is a **projection index** (0–100 scale) from a simple ramp model for dashboard storytelling.
    """
    oid = int(organization_id)
    n = max(7, min(int(days), 90))
    factory: sessionmaker[Session] | None = _session_factory or get_session_factory()  # type: ignore[assignment]
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}

    now = _utc_now()
    labels: list[str] = []
    revenue: list[float] = []
    expenses: list[float] = []
    solar_roi: list[float] = []

    with factory() as session:
        for i in range(n):
            day_start = _start_of_today_utc(now) - timedelta(days=(n - 1 - i))
            day_end_exclusive = day_start + timedelta(days=1)
            labels.append(day_start.strftime("%b %d"))
            rev = _sum_revenue(session, organization_id=oid, start=day_start, end=day_end_exclusive)
            r = float(rev)
            revenue.append(round(r, 2))
            opex = round(r * 0.32, 2)
            expenses.append(opex)
            base = 18.0 + (i / max(n - 1, 1)) * 62.0
            jitter = (oid % 7) * 0.4 + (i % 3) * 0.9
            solar_roi.append(round(min(95.0, base + jitter), 1))

    return {
        "ok": True,
        "organization_id": oid,
        "as_of_utc": now.isoformat(),
        "labels": labels,
        "revenue_inr": revenue,
        "expenses_inr_est": expenses,
        "solar_roi_projection": solar_roi,
        "note": "Expenses are estimated from revenue; solar ROI is a projection index for planning.",
    }
