"""
Personal OS engagement: streak, daily score components, one-click actions, suggestion feedback.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from core.database import get_session_factory
from core.db.models import LearningLog, PersonalEngagement, PersonalMission, PersonalSuggestionFeedback
from services import life_os_service


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def touch_streak_sync(user_id: int) -> dict[str, Any]:
    """
    Mark today as an active day and update consecutive-day streak.
    Returns ``{ "streak_days", "extra" }`` (extra may include actions_today).
    """
    uid = int(user_id)
    if uid <= 0:
        return {"streak_days": 0, "extra": {}}

    factory = get_session_factory()
    if factory is None:
        return {"streak_days": 0, "extra": {}}

    today = _today_utc()
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
                session.flush()
                return {"streak_days": int(row.streak_days), "extra": dict(row.extra or {})}

            last = row.last_active_date
            if last is None:
                row.streak_days = max(1, int(row.streak_days or 0))
            elif last == today:
                pass
            elif last == today - timedelta(days=1):
                row.streak_days = int(row.streak_days or 0) + 1
            else:
                row.streak_days = 1
            row.last_active_date = today
            session.flush()
            return {"streak_days": int(row.streak_days), "extra": dict(row.extra or {})}


def _actions_today_count(extra: dict[str, Any], today: date) -> int:
    block = extra.get("actions_today") if isinstance(extra.get("actions_today"), dict) else {}
    if block.get("date") != today.isoformat():
        return 0
    return int(block.get("count") or 0)


def increment_actions_today_sync(user_id: int) -> None:
    uid = int(user_id)
    if uid <= 0:
        return
    factory = get_session_factory()
    if factory is None:
        return
    today = _today_utc()
    with factory() as session:
        with session.begin():
            row = session.get(PersonalEngagement, uid)
            if row is None:
                row = PersonalEngagement(user_id=uid, last_active_date=today, streak_days=1, extra={})
                session.add(row)
            ex = dict(row.extra or {})
            block = ex.get("actions_today") if isinstance(ex.get("actions_today"), dict) else {}
            if block.get("date") != today.isoformat():
                block = {"date": today.isoformat(), "count": 0}
            block["count"] = int(block.get("count") or 0) + 1
            ex["actions_today"] = block
            row.extra = ex
            session.flush()


def compute_daily_score(payload: dict[str, Any], engagement_extra: dict[str, Any]) -> dict[str, Any]:
    """
    Heuristic 0–100 score: sales, stock health, task load, habits/tasks completed, actions taken.
    """
    oid = int(payload.get("organization_id") or 0)
    sales = payload.get("today_sales") or {}
    low = payload.get("low_stock") or {}
    n_tasks = len(payload.get("tasks") or [])
    n_low = int(low.get("count") or 0)
    habits_done = int(payload.get("habits_completed_today") or 0)
    tasks_done = int(payload.get("tasks_completed_today") or 0)
    actions_ct = _actions_today_count(engagement_extra, _today_utc())

    rev_ok = isinstance(sales, dict) and sales.get("ok")
    rev_block = sales.get("revenue_inr") if isinstance(sales.get("revenue_inr"), dict) else {}
    raw = rev_block.get("today")
    rev_num: float | None = None
    if rev_ok and raw is not None:
        try:
            rev_num = float(str(raw).replace(",", "").replace("₹", "").strip() or "0")
        except ValueError:
            rev_num = None

    parts: dict[str, int] = {}
    score = 0

    if oid > 0 and rev_num is not None:
        if rev_num > 0:
            parts["sales"] = 35
            score += 35
        else:
            parts["sales"] = 0
    else:
        parts["sales"] = 0

    if oid > 0:
        if n_low == 0:
            parts["stock_clear"] = 25
            score += 25
        else:
            pen = min(25, 5 * min(n_low, 5))
            parts["stock_clear"] = max(0, 25 - pen)
            score += parts["stock_clear"]
    else:
        parts["stock_clear"] = 0

    if n_tasks <= 2:
        parts["task_load"] = 15
        score += 15
    elif n_tasks <= 5:
        parts["task_load"] = 10
        score += 10
    else:
        parts["task_load"] = 5
        score += 5

    if habits_done > 0:
        parts["habits"] = min(10, 5 * min(habits_done, 2))
        score += parts["habits"]
    else:
        parts["habits"] = 0

    if tasks_done > 0:
        parts["tasks_done"] = min(10, 5 * min(tasks_done, 2))
        score += parts["tasks_done"]
    else:
        parts["tasks_done"] = 0

    if actions_ct > 0:
        parts["actions"] = min(10, 5 * min(actions_ct, 2))
        score += parts["actions"]
    else:
        parts["actions"] = 0

    score = max(0, min(100, score))
    return {"daily_score": score, "daily_score_breakdown": parts}


def record_suggestion_feedback_sync(
    *,
    user_id: int,
    organization_id: int | None,
    suggestion: str,
    helpful: bool,
) -> dict[str, Any]:
    uid = int(user_id)
    if uid <= 0:
        return {"ok": False, "error": "authentication required"}
    text = (suggestion or "").strip()[:4000]
    if not text:
        return {"ok": False, "error": "suggestion required"}

    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "database not configured"}

    oid = int(organization_id) if organization_id and int(organization_id) > 0 else None
    with factory() as session:
        with session.begin():
            fb = PersonalSuggestionFeedback(
                user_id=uid,
                organization_id=oid,
                suggestion_text=text,
                helpful=bool(helpful),
            )
            session.add(fb)
            session.flush()
            fid = int(fb.id)
            if oid is not None:
                session.add(
                    LearningLog(
                        organization_id=oid,
                        approval_id=None,
                        outcome="positive" if helpful else "negative",
                        action_type="personal_suggestion_feedback",
                        lesson_summary=text[:2000],
                        context={"channel": "personal_os", "feedback_id": fid},
                        result={"helpful": helpful},
                        user_feedback=text[:4000] if not helpful else None,
                        resolved_by_user_id=uid,
                    )
                )
    return {"ok": True, "feedback_id": fid}


def execute_personal_action_sync(
    *,
    user_id: int,
    organization_id: int,
    action: str,
    item: str | None = None,
    quantity: float | None = None,
    mission_id: int | None = None,
    title: str | None = None,
    feedback: str | None = None,
) -> dict[str, Any]:
    """Dispatch one-click personal actions (restock, UI hints, complete task)."""
    uid = int(user_id)
    oid = int(organization_id)
    act = (action or "").strip().lower()
    if uid <= 0:
        return {"ok": False, "error": "authentication required", "executed": False}

    if act in ("restock", "inventory_add", "add_stock"):
        sku = (item or "").strip()
        if not sku:
            return {"ok": False, "error": "item (sku name) required", "executed": False}
        if oid <= 0:
            return {"ok": False, "error": "organization required for inventory", "executed": False}
        qty = float(quantity) if quantity is not None else 10.0
        if qty <= 0:
            qty = 10.0
        from services.inventory_service import add_inventory_sync

        out = add_inventory_sync(
            organization_id=oid,
            sku_name=sku,
            quantity=qty,
            location="",
            user_id=uid,
        )
        if not out.get("ok"):
            return {**out, "executed": False}
        increment_actions_today_sync(uid)
        return {"ok": True, "executed": True, "detail": out, "channel": "inventory_add"}

    if act in ("record_sale", "open_pos", "quick_sell"):
        increment_actions_today_sync(uid)
        return {
            "ok": True,
            "executed": False,
            "action_type": "ui",
            "ui_hint": "command_deck",
            "message": "Open Command deck → Quick sell (POS) to record a sale.",
        }

    if act in ("open_tasks", "focus_tasks", "open_life_os"):
        increment_actions_today_sync(uid)
        return {
            "ok": True,
            "executed": False,
            "action_type": "ui",
            "ui_hint": "life_os",
            "message": "Use Life OS missions or dashboard to check off tasks.",
        }

    if act in ("complete_task", "done_task"):
        mid = int(mission_id) if mission_id is not None else 0
        if mid <= 0:
            return {"ok": False, "error": "mission_id required", "executed": False}
        factory = get_session_factory()
        if factory is None:
            return {"ok": False, "error": "database not configured", "executed": False}
        with factory() as session:
            row = session.get(PersonalMission, mid)
            if row is None or int(row.user_id) != uid:
                return {"ok": False, "error": "mission not found", "executed": False}
            title = row.title
        ok, msg, _, _ = life_os_service.upsert_personal_mission(
            user_id=uid,
            mission_id=mid,
            title=title,
            status="done",
        )
        if not ok:
            return {"ok": False, "error": msg, "executed": False}
        increment_actions_today_sync(uid)
        return {"ok": True, "executed": True, "detail": {"mission_id": mid, "status": "done"}}

    if act in ("add_task", "create_task", "new_mission"):
        t = (title or item or "").strip()
        if not t:
            return {"ok": False, "error": "title (or item) required for new task", "executed": False}
        ok, msg, mid = life_os_service.create_personal_mission(user_id=uid, title=t)
        if not ok:
            return {"ok": False, "error": msg, "executed": False}
        increment_actions_today_sync(uid)
        return {"ok": True, "executed": True, "detail": {"mission_id": mid, "title": t}}

    if act in ("research_feedback", "research_correction"):
        from services.executive_os_service import save_research_correction_sync

        fb = (feedback or title or item or "").strip()
        if not fb:
            return {"ok": False, "error": "research feedback text required", "executed": False}
        if oid <= 0:
            return {"ok": False, "error": "organization required for research feedback", "executed": False}
        out = save_research_correction_sync(
            user_id=uid,
            organization_id=oid,
            feedback_text=fb,
            source="command_bar",
            priority=10,
        )
        if not out.get("ok"):
            return {**out, "executed": False}
        increment_actions_today_sync(uid)
        return {
            "ok": True,
            "executed": True,
            "detail": out,
            "message": "Research feedback saved; future reports will prioritize it.",
        }

    if act in ("sign_in", "noop"):
        return {"ok": True, "executed": False, "action_type": "ui", "message": "No server action."}

    return {"ok": False, "error": f"unknown action: {act}", "executed": False}
