"""
Life memory — long-horizon personal context stored in ``PersonalEngagement.extra`` (no new tables).

Kinds: ``goal``, ``habit``, ``decision``, ``reflection``, ``pattern``, ``note``.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from core.database import get_session_factory
from core.db.models import Habit, HabitLog, PersonalEngagement, PersonalMission

LIFE_EVENTS_KEY = "life_memory_events"
MAX_STORED_EVENTS = 120


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_life_event_sync(
    user_id: int,
    kind: str,
    summary: str,
    *,
    payload: dict[str, Any] | None = None,
    organization_id: int | None = None,
) -> dict[str, Any]:
    """
    Append a compact life event. Merges into existing ``PersonalEngagement.extra`` keys.
    """
    uid = int(user_id)
    if uid <= 0:
        return {"ok": False, "error": "invalid user"}
    k = (kind or "note").strip().lower()[:64]
    text = (summary or "").strip()[:2000]
    if not text:
        return {"ok": False, "error": "summary required"}

    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "database not configured"}

    entry: dict[str, Any] = {
        "at": _utc_now_iso(),
        "kind": k,
        "summary": text,
        "payload": dict(payload or {}),
    }
    if organization_id is not None and int(organization_id) > 0:
        entry["organization_id"] = int(organization_id)

    with factory() as session:
        with session.begin():
            row = session.get(PersonalEngagement, uid)
            if row is None:
                row = PersonalEngagement(user_id=uid, extra={})
                session.add(row)
                session.flush()
            ex = dict(row.extra or {})
            events = list(ex.get(LIFE_EVENTS_KEY) or [])
            if not isinstance(events, list):
                events = []
            events.insert(0, entry)
            ex[LIFE_EVENTS_KEY] = events[:MAX_STORED_EVENTS]
            row.extra = ex
            session.flush()
    return {"ok": True, "stored": True}


def _load_life_events(user_id: int, limit: int = 80) -> list[dict[str, Any]]:
    uid = int(user_id)
    if uid <= 0:
        return []
    factory = get_session_factory()
    if factory is None:
        return []
    with factory() as session:
        row = session.get(PersonalEngagement, uid)
        if row is None:
            return []
        ex = row.extra or {}
        raw = ex.get(LIFE_EVENTS_KEY) or []
        if not isinstance(raw, list):
            return []
        out: list[dict[str, Any]] = []
        for item in raw[:limit]:
            if isinstance(item, dict):
                out.append(item)
        return out


def get_user_profile_sync(user_id: int, organization_id: int = 0) -> dict[str, Any]:
    """
    Aggregate goals (open missions), habit history, logged decisions, and quick stats.
    """
    uid = int(user_id)
    oid = int(organization_id)
    empty: dict[str, Any] = {
        "long_term_goals": [],
        "habits_history": {"active_habits": 0, "check_ins_last_14d": 0, "top_habits": []},
        "past_decisions": [],
        "recent_notes": [],
        "stats": {"open_missions": 0, "life_events_stored": 0},
    }
    if uid <= 0:
        return empty

    events = _load_life_events(uid)
    decisions = [e for e in events if str(e.get("kind") or "").lower() == "decision"][:20]
    notes = [e for e in events if str(e.get("kind") or "").lower() in ("note", "reflection", "pattern")][:12]

    goals: list[dict[str, Any]] = []
    habits_block = empty["habits_history"]
    open_missions = 0

    factory = get_session_factory()
    if factory is not None:
        with factory() as session:
            for m in session.execute(
                select(PersonalMission)
                .where(
                    PersonalMission.user_id == uid,
                    PersonalMission.status.in_(("open", "in_progress")),
                )
                .order_by(
                    PersonalMission.deadline.is_(None),
                    PersonalMission.deadline.asc(),
                    PersonalMission.created_at.desc(),
                )
                .limit(15)
            ).scalars():
                open_missions += 1
                goals.append(
                    {
                        "id": int(m.id),
                        "title": (m.title or "")[:200],
                        "deadline": m.deadline.isoformat() if m.deadline else None,
                        "status": m.status,
                    }
                )
            since = datetime.now(timezone.utc) - timedelta(days=14)
            habit_rows = list(session.execute(select(Habit).where(Habit.user_id == uid)).scalars().all())
            active = [h for h in habit_rows if h.is_active]
            habits_block["active_habits"] = len(active)
            if active:
                counts: dict[int, int] = defaultdict(int)
                for h in active:
                    c = int(
                        session.execute(
                            select(func.count())
                            .select_from(HabitLog)
                            .where(HabitLog.habit_id == h.id, HabitLog.completed_at >= since)
                        ).scalar()
                        or 0
                    )
                    counts[int(h.id)] = c
                top = sorted(active, key=lambda hh: -counts.get(int(hh.id), 0))[:5]
                habits_block["top_habits"] = [
                    {"id": int(h.id), "title": (h.title or "")[:120], "completions_14d": counts.get(int(h.id), 0)}
                    for h in top
                ]
                habits_block["check_ins_last_14d"] = sum(counts.values())

    return {
        "long_term_goals": goals[:8],
        "habits_history": habits_block,
        "past_decisions": [{"at": d.get("at"), "summary": d.get("summary")} for d in decisions],
        "recent_notes": [{"at": n.get("at"), "kind": n.get("kind"), "summary": n.get("summary")} for n in notes],
        "stats": {
            "open_missions": open_missions,
            "life_events_stored": len(events),
            "organization_id": oid,
        },
    }


def detect_patterns_sync(user_id: int, organization_id: int = 0) -> dict[str, Any]:
    """
    Lightweight pattern hints from missions, habits, and life events (deterministic).
    """
    uid = int(user_id)
    if uid <= 0:
        return {"signals": [], "summary": "Sign in to build personal patterns.", "confidence": "none"}

    profile = get_user_profile_sync(uid, organization_id)
    signals: list[str] = []
    hh = profile.get("habits_history") or {}
    if int(hh.get("active_habits") or 0) >= 3 and int(hh.get("check_ins_last_14d") or 0) >= 10:
        signals.append("strong_habit_consistency")
    elif int(hh.get("active_habits") or 0) >= 1 and int(hh.get("check_ins_last_14d") or 0) <= 2:
        signals.append("habit_drift")

    om = int((profile.get("stats") or {}).get("open_missions") or 0)
    if om >= 7:
        signals.append("mission_backlog")
    elif om == 0:
        signals.append("clear_task_queue")

    events = _load_life_events(uid, limit=40)
    kinds = [str(e.get("kind") or "").lower() for e in events]
    if kinds.count("decision") >= 4:
        signals.append("frequent_explicit_decisions")

    summary_parts: list[str] = []
    if "strong_habit_consistency" in signals:
        summary_parts.append("Habit rhythm looks steady — protect it with one anchor time.")
    if "habit_drift" in signals:
        summary_parts.append("Habits are light lately — one tiny win today resets the streak.")
    if "mission_backlog" in signals:
        summary_parts.append("Many open missions — batch by theme and close one small item.")
    if "clear_task_queue" in signals:
        summary_parts.append("Task queue is clear — good window for planning or deep work.")
    if not summary_parts:
        summary_parts.append("Patterns still forming — log decisions and goals as you go.")

    conf = "medium" if len(signals) >= 2 else "low"
    return {
        "signals": signals,
        "summary": " ".join(summary_parts),
        "confidence": conf,
    }
