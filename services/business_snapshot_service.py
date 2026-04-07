"""
Single JSON **Business OS snapshot** for dashboards, command center, and AI (Phase 4).

All entrypoints are synchronous (use ``asyncio.to_thread`` from FastAPI if needed).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from core.database import get_session_factory
from core.db.models import AttendanceLog, Bill, StaffProfile
from services.analytics_service import list_low_stock_alerts_sync
from services.economics_service import get_business_margin


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _start_of_today_utc(now: datetime) -> datetime:
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def daily_sales_target_inr() -> Decimal:
    raw = (os.getenv("THIRAMAI_DAILY_SALES_TARGET_INR") or "0").strip()
    try:
        return Decimal(str(raw)).quantize(Decimal("0.01"))
    except Exception:
        return Decimal("0")


def _sum_revenue_today(session: Session, *, organization_id: int, now: datetime) -> Decimal:
    start = _start_of_today_utc(now)
    end = now + timedelta(microseconds=1)
    q = select(func.coalesce(func.sum(Bill.total_amount), 0)).where(
        Bill.organization_id == int(organization_id),
        Bill.created_at >= start,
        Bill.created_at < end,
    )
    v = session.execute(q).scalar_one()
    return Decimal(str(v or 0)).quantize(Decimal("0.01"))


def attendance_summary_today(
    session: Session,
    *,
    organization_id: int,
    now: datetime,
) -> dict[str, Any]:
    oid = int(organization_id)
    day_start = _start_of_today_utc(now)
    day_end = day_start + timedelta(days=1)

    active_n = session.execute(
        select(func.count())
        .select_from(StaffProfile)
        .where(StaffProfile.organization_id == oid, StaffProfile.status == "active")
    ).scalar_one()
    active = int(active_n or 0)

    # Distinct staff profiles with a check-in today (any status except explicit absent still counts as "showed")
    checked_rows = session.execute(
        select(AttendanceLog.staff_id)
        .join(StaffProfile, StaffProfile.id == AttendanceLog.staff_id)
        .where(
            StaffProfile.organization_id == oid,
            AttendanceLog.check_in >= day_start,
            AttendanceLog.check_in < day_end,
        )
        .distinct()
    ).all()
    checked_in = len({int(r[0]) for r in checked_rows if r[0] is not None})

    absent_estimate = max(0, active - checked_in) if active else 0
    return {
        "active_staff": active,
        "checked_in_today": checked_in,
        "absent_estimate": absent_estimate,
        "as_of_utc": now.isoformat(),
    }


def build_business_snapshot(
    organization_id: int,
    *,
    low_stock_threshold: int = 5,
    _as_of: datetime | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """
    One object with: today's sales vs target, low stock, attendance summary, monthly net profit / margin.

    When ``REDIS_URL`` is set and ``use_cache`` is True, responses are cached (default TTL 5 minutes).
    """
    oid = int(organization_id)
    thr = int(low_stock_threshold)
    now = _as_of if _as_of is not None else _utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    from core.redis_cache import cache_get_json, cache_set_json, snapshot_cache_ttl_sec

    cache_key = f"thiramai:cache:biz_snap:{oid}:{thr}"
    if use_cache:
        hit = cache_get_json(cache_key)
        if isinstance(hit, dict) and hit.get("ok") is True:
            return hit

    factory: sessionmaker[Session] | None = get_session_factory()  # type: ignore[assignment]
    if factory is None:
        return {
            "ok": False,
            "error": "DATABASE_URL is not configured",
            "organization_id": oid,
        }

    target = daily_sales_target_inr()
    with factory() as session:
        actual = _sum_revenue_today(session, organization_id=oid, now=now)
        att = attendance_summary_today(session, organization_id=oid, now=now)

    low = list_low_stock_alerts_sync(oid, threshold=thr)
    profit = get_business_margin(oid, _as_of=now)

    pct_target: float | None
    if target > 0:
        pct_target = float((actual / target * Decimal("100")).quantize(Decimal("0.01")))
    else:
        pct_target = None

    out: dict[str, Any] = {
        "ok": True,
        "organization_id": oid,
        "as_of_utc": now.isoformat(),
        "sales_today": {
            "actual_inr": str(actual),
            "target_inr": str(target),
            "percent_of_target": pct_target,
        },
        "low_stock_alerts": low,
        "attendance_today": att,
        "profit_month": profit,
    }
    if use_cache:
        cache_set_json(cache_key, out, ttl_sec=snapshot_cache_ttl_sec())
    return out
