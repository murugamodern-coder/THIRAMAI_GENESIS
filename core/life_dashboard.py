"""
Life dashboard scores — health (from logs when present), productivity, finance signal, workload.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import HealthLog


def _parse_revenue_today(sales: dict[str, Any]) -> float | None:
    if not isinstance(sales, dict) or not sales.get("ok"):
        return None
    block = sales.get("revenue_inr") if isinstance(sales.get("revenue_inr"), dict) else {}
    raw = block.get("today")
    if raw is None:
        return None
    try:
        return float(str(raw).replace(",", "").replace("₹", "").strip() or "0")
    except ValueError:
        return None


def _health_score_from_logs(user_id: int) -> tuple[int | None, str]:
    uid = int(user_id)
    if uid <= 0:
        return None, "no_user"
    factory = get_session_factory()
    if factory is None:
        return None, "no_db"

    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=7)

    with factory() as session:
        rows = list(
            session.execute(
                select(HealthLog).where(HealthLog.user_id == uid, HealthLog.logged_on >= start)
            )
            .scalars()
            .all()
        )

    if not rows:
        return None, "no_health_logs"

    sleep_vals: list[float] = []
    stress_vals: list[int] = []
    for r in rows:
        if r.sleep_hours is not None:
            try:
                sleep_vals.append(float(r.sleep_hours))
            except (TypeError, ValueError):
                pass
        if r.stress_1_10 is not None:
            try:
                stress_vals.append(int(r.stress_1_10))
            except (TypeError, ValueError):
                pass

    score = 70
    if sleep_vals:
        avg_sleep = sum(sleep_vals) / len(sleep_vals)
        if avg_sleep >= 7:
            score += 12
        elif avg_sleep >= 6:
            score += 6
        else:
            score -= 8
    if stress_vals:
        avg_s = sum(stress_vals) / len(stress_vals)
        if avg_s <= 4:
            score += 8
        elif avg_s >= 8:
            score -= 10

    return max(0, min(100, int(score))), "from_health_logs"


def build_life_dashboard(
    payload: dict[str, Any],
    *,
    user_id: int,
    organization_id: int,
) -> dict[str, Any]:
    """
    Composite dashboard block for ``GET /personal/today`` (`life_score` root key).
    """
    uid = int(user_id)
    oid = int(organization_id)
    tasks = payload.get("tasks") if isinstance(payload.get("tasks"), list) else []
    reminders = payload.get("reminders") if isinstance(payload.get("reminders"), list) else []
    low = payload.get("low_stock") if isinstance(payload.get("low_stock"), dict) else {}
    sales = payload.get("today_sales") or {}
    if not isinstance(sales, dict):
        sales = {}

    daily_score = int(payload.get("daily_score") or 0)
    productivity_score = daily_score

    health_score, health_source = (None, "mock")
    if uid > 0:
        hs, src = _health_score_from_logs(uid)
        if hs is not None:
            health_score = hs
            health_source = src
    if health_score is None:
        health_score = 72
        health_source = "mock_default"

    rev = _parse_revenue_today(sales)
    if oid <= 0:
        financial_signal = "personal_only"
    elif rev is None:
        financial_signal = "unknown"
    elif rev > 0:
        financial_signal = "positive_flow"
    else:
        financial_signal = "needs_attention"

    n_low = int(low.get("count") or 0)
    load = len(tasks) + len(reminders) // 2 + n_low * 2
    if load >= 12:
        workload_level = "critical"
    elif load >= 7:
        workload_level = "high"
    elif load >= 3:
        workload_level = "moderate"
    else:
        workload_level = "light"

    return {
        "health_score": health_score,
        "health_source": health_source,
        "productivity_score": productivity_score,
        "financial_signal": financial_signal,
        "workload_level": workload_level,
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
    }
