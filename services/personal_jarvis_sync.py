"""
Jarvis layer: yesterday follow-ups (suggestion accountability) + snapshot persistence in ``personal_engagement.extra``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from core.database import get_session_factory
from core.personal_memory_engine import learn_user_patterns_sync
from core.db.models import Habit, HabitLog, PersonalEngagement, PersonalMission
from services.analytics_service import compute_dashboard_summary_sync
from services.life_os_service import MISSION_OPEN_STATUSES


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _parse_today_revenue(sales: Any) -> float | None:
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


def _sku_still_low(sku: str, payload: dict[str, Any]) -> bool:
    low = payload.get("low_stock") or {}
    target = (sku or "").strip().lower()
    if not target:
        return False
    for it in low.get("items") or []:
        if (str(it.get("sku_name") or "").strip().lower() == target):
            return True
    return False


def _mission_still_open(mission_id: int, tasks: list[dict[str, Any]]) -> bool:
    mid = int(mission_id)
    for t in tasks:
        if int(t.get("id") or 0) == mid:
            return True
    return False


def _serialize_actionable(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in items:
        if not isinstance(s, dict):
            continue
        out.append(
            {
                "text": (s.get("text") or "")[:500],
                "action": s.get("action"),
                "body": s.get("body") if isinstance(s.get("body"), dict) else {},
            }
        )
    return out[:24]


def compute_yesterday_followups_sync(user_id: int, today_payload: dict[str, Any]) -> list[str]:
    """If yesterday's snapshot exists, compare to today's state and return reminder lines."""
    uid = int(user_id)
    if uid <= 0:
        return []

    yesterday = _today_utc() - timedelta(days=1)
    factory = get_session_factory()
    if factory is None:
        return []

    with factory() as session:
        row = session.get(PersonalEngagement, uid)
        if row is None:
            return []
        ex = row.extra if isinstance(row.extra, dict) else {}
        prev = ex.get("jarvis_prev_snapshot")
        if not isinstance(prev, dict):
            return []
        if prev.get("for_date") != yesterday.isoformat():
            return []

    items = prev.get("items") if isinstance(prev.get("items"), list) else []
    msgs: list[str] = []
    sales = today_payload.get("today_sales") or {}
    rev = _parse_today_revenue(sales)
    tasks = today_payload.get("tasks") if isinstance(today_payload.get("tasks"), list) else []

    fl = prev.get("focus_lock")
    if isinstance(fl, dict):
        title = (fl.get("title") or "").strip()
        mid = fl.get("mission_id")
        if mid is not None and title and _mission_still_open(int(mid), tasks):
            msgs.append(
                f"Your focus lock was still «{title}» — it's waiting. You can finish one more today."
            )

    for it in items:
        if not isinstance(it, dict):
            continue
        act = (it.get("action") or "").strip().lower()
        body = it.get("body") if isinstance(it.get("body"), dict) else {}
        if act == "restock":
            sku = (body.get("item") or "").strip()
            if sku and _sku_still_low(sku, today_payload):
                msgs.append(f"Yesterday you were nudged to restock {sku} — it's still low today.")
        elif act == "complete_task":
            mid = body.get("mission_id")
            if mid is not None and _mission_still_open(int(mid), tasks):
                msgs.append("Yesterday's plan included finishing a task — that mission is still open.")
        elif act == "record_sale":
            if rev is not None and rev <= 0:
                msgs.append("Yesterday we suggested logging a sale — still no sales recorded today.")

    return msgs[:8]


def persist_today_jarvis_snapshot_sync(
    user_id: int,
    actionable_suggestions: list[dict[str, Any]],
    focus_lock_meta: dict[str, Any] | None = None,
) -> None:
    """Store today's actionable summary + focus lock for tomorrow's follow-up pass."""
    uid = int(user_id)
    if uid <= 0:
        return
    factory = get_session_factory()
    if factory is None:
        return
    today = _today_utc()
    fl_block: dict[str, Any] | None = None
    if isinstance(focus_lock_meta, dict) and focus_lock_meta.get("title"):
        fl_block = {
            "mission_id": focus_lock_meta.get("mission_id"),
            "title": str(focus_lock_meta.get("title") or "")[:240],
            "sku": (str(focus_lock_meta.get("sku") or "").strip()[:120] or None),
        }
    with factory() as session:
        with session.begin():
            row = session.get(PersonalEngagement, uid)
            if row is None:
                row = PersonalEngagement(
                    user_id=uid,
                    last_active_date=today,
                    streak_days=1,
                    extra={},
                )
                session.add(row)
            ex = dict(row.extra or {})
            ex["jarvis_prev_snapshot"] = {
                "for_date": today.isoformat(),
                "items": _serialize_actionable(actionable_suggestions),
                "focus_lock": fl_block,
            }
            row.extra = ex
            session.flush()


def count_weekly_completions_sync(user_id: int, *, days: int = 7) -> dict[str, int]:
    """Habit logs + personal missions closed in the rolling window."""
    uid = int(user_id)
    out = {"habit_completions": 0, "missions_completed": 0}
    if uid <= 0:
        return out
    factory = get_session_factory()
    if factory is None:
        return out
    start = datetime.now(timezone.utc) - timedelta(days=days)
    with factory() as session:
        hc = session.execute(
            select(func.count())
            .select_from(HabitLog)
            .join(Habit, HabitLog.habit_id == Habit.id)
            .where(
                Habit.user_id == uid,
                HabitLog.completed_at >= start,
            )
        ).scalar()
        out["habit_completions"] = int(hc or 0)

        mc = session.execute(
            select(func.count())
            .select_from(PersonalMission)
            .where(
                PersonalMission.user_id == uid,
                ~PersonalMission.status.in_(tuple(MISSION_OPEN_STATUSES)),
                PersonalMission.updated_at >= start,
            )
        ).scalar()
        out["missions_completed"] = int(mc or 0)
    return out


def build_weekly_personal_report_sync(user_id: int, organization_id: int) -> dict[str, Any]:
    """Rolling 7-day snapshot for Personal Jarvis weekly insight."""
    oid = int(organization_id)
    counts = count_weekly_completions_sync(user_id, days=7)
    sales_block: dict[str, Any] = {}
    if oid > 0:
        sales_block = compute_dashboard_summary_sync(oid, low_stock_threshold=5)

    rev_week = None
    if isinstance(sales_block, dict) and sales_block.get("ok"):
        r = (sales_block.get("revenue_inr") or {}).get("this_week")
        rev_week = str(r) if r is not None else None

    memory = learn_user_patterns_sync(user_id, organization_id)
    improvement = memory.get("preferred_summary") or "Log feedback on suggestions to sharpen next week's nudges."
    if counts["missions_completed"] == 0 and counts["habit_completions"] == 0:
        improvement = "Try closing one mission or logging a habit this week — small wins lift your score."
    elif rev_week and str(rev_week).replace(",", "").strip() in ("0", "0.0", ""):
        improvement = "Revenue this week looks quiet — schedule one follow-up or record every cash sale."

    return {
        "ok": True,
        "period_days": 7,
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "total_sales_week_inr_display": rev_week,
        "tasks_completed_approx": counts["missions_completed"],
        "habit_completions_week": counts["habit_completions"],
        "improvement_suggestion": improvement,
        "memory_stats": memory.get("stats"),
    }
