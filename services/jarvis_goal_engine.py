"""
Upgrade 2.2 — Goal-driven engine: persisted goals, subtasks, progress, daily resume hints.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.database import get_session_factory
from core.db.models import JarvisGoal, JarvisGoalSubtask

_log = logging.getLogger("thiramai.jarvis_goal_engine")

_GOAL_ACTIVE = frozenset({"open", "in_progress"})
_GOAL_DONE = frozenset({"completed", "cancelled"})


def _infer_goal_type(description: str) -> str:
    d = (description or "").lower()
    if any(x in d for x in ("profit", "revenue", "sales", "turnover")):
        return "revenue"
    if any(x in d for x in ("cost", "save", "reduce expense", "cut")):
        return "cost"
    if any(x in d for x in ("emi", "loan", "debt")):
        return "finance"
    return "custom"


def _extract_target_hint(description: str) -> str | None:
    m = re.search(r"[₹]?\s*([\d,]+(?:\.\d+)?)\s*(?:k|lac|lakh|lacs)?", description or "", re.I)
    if not m:
        return None
    return m.group(1).replace(",", "")


def _default_subtask_titles(description: str, goal_type: str) -> list[str]:
    d = (description or "").lower()
    gt = (goal_type or "custom").lower()
    if gt == "revenue" or "profit" in d or "revenue" in d:
        return [
            "Review top revenue SKUs / services and pricing headroom",
            "Collect overdue receivables older than one week",
            "Schedule one upsell or cross-sell outreach block",
            "Align production or fulfillment with demand forecast",
        ]
    if gt == "cost" or "cost" in d or "save" in d:
        return [
            "List top 5 variable costs for the month",
            "Negotiate or re-quote one supplier contract",
            "Eliminate one recurring low-use subscription",
        ]
    if gt == "finance" or "emi" in d:
        return [
            "Confirm EMI dates and bank balance buffers",
            "Automate or calendar a transfer reminder 48h early",
        ]
    return [
        "Define one measurable checkpoint for this week",
        "Block calendar time for execution",
        "Review outcome vs target mid-month",
    ]


def create_goal_sync(
    *,
    user_id: int,
    description: str,
    goal_type: str | None = None,
    organization_id: int | None = None,
    target_value: str | None = None,
    deadline: date | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a goal row (status ``open``)."""
    uid = int(user_id)
    desc = (description or "").strip()
    if uid <= 0 or not desc:
        return {"ok": False, "error": "user_id and description required"}
    gt = (goal_type or _infer_goal_type(desc)).strip()[:64] or "custom"
    tv = (target_value or _extract_target_hint(desc) or "").strip()[:512] or None
    oid = int(organization_id) if organization_id and int(organization_id) > 0 else None
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "database not configured"}
    with factory() as session:
        with session.begin():
            row = JarvisGoal(
                user_id=uid,
                organization_id=oid,
                goal_type=gt,
                description=desc[:8000],
                target_value=tv,
                deadline=deadline,
                status="open",
                progress={"percent": 0, "notes": ""},
                meta=meta if isinstance(meta, dict) else None,
            )
            session.add(row)
            session.flush()
            gid = int(row.id)
        return {"ok": True, "goal_id": gid}


def break_into_subtasks_sync(*, goal_id: int, user_id: int) -> dict[str, Any]:
    """Create default subtasks for a goal if none exist."""
    gid = int(goal_id)
    uid = int(user_id)
    if gid <= 0 or uid <= 0:
        return {"ok": False, "error": "invalid ids"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "database not configured"}
    with factory() as session:
        with session.begin():
            goal = session.get(JarvisGoal, gid)
            if goal is None or int(goal.user_id) != uid:
                return {"ok": False, "error": "goal not found"}
            existing = session.scalars(
                select(JarvisGoalSubtask).where(JarvisGoalSubtask.goal_id == gid).limit(1)
            ).first()
            if existing:
                return {"ok": True, "skipped": "subtasks_already_exist", "goal_id": gid}
            titles = _default_subtask_titles(goal.description, goal.goal_type)
            for i, title in enumerate(titles):
                session.add(JarvisGoalSubtask(goal_id=gid, title=title[:512], sort_order=i, status="pending"))
            goal.status = "in_progress"
        return {"ok": True, "goal_id": gid, "subtasks_created": len(titles)}


def track_progress_sync(*, goal_id: int, user_id: int) -> dict[str, Any]:
    """Recompute ``goal.progress`` from subtask completion ratio."""
    gid = int(goal_id)
    uid = int(user_id)
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "database not configured"}
    with factory() as session:
        with session.begin():
            goal = session.get(JarvisGoal, gid)
            if goal is None or int(goal.user_id) != uid:
                return {"ok": False, "error": "goal not found"}
            subs = list(session.scalars(select(JarvisGoalSubtask).where(JarvisGoalSubtask.goal_id == gid)).all())
            if not subs:
                return {"ok": True, "goal_id": gid, "percent": float((goal.progress or {}).get("percent") or 0)}
            done = sum(1 for s in subs if (s.status or "").lower() == "done")
            pct = round(100.0 * done / max(1, len(subs)), 1)
            prog = dict(goal.progress or {})
            prog["percent"] = pct
            prog["done_subtasks"] = done
            prog["total_subtasks"] = len(subs)
            prog["as_of"] = datetime.now(timezone.utc).isoformat()
            goal.progress = prog
            if pct >= 99.5:
                goal.status = "completed"
            elif goal.status == "open":
                goal.status = "in_progress"
            st_out = goal.status
        if st_out == "completed":
            try:
                from services.jarvis_autonomous_agent import record_goal_long_term_learning_sync

                record_goal_long_term_learning_sync(user_id=uid)
            except Exception:
                pass
        return {"ok": True, "goal_id": gid, "percent": pct, "status": st_out}


def auto_continue_incomplete_goals_sync(*, user_id: int, limit: int = 8) -> list[dict[str, Any]]:
    """
    Resume unfinished work: next pending subtask per active goal.

    Used by the autonomous agent to enqueue safe follow-ups.
    """
    uid = int(user_id)
    if uid <= 0:
        return []
    factory = get_session_factory()
    if factory is None:
        return []
    lim = max(1, min(int(limit), 24))
    out: list[dict[str, Any]] = []
    with factory() as session:
        goals = list(
            session.scalars(
                select(JarvisGoal)
                .options(selectinload(JarvisGoal.subtasks))
                .where(JarvisGoal.user_id == uid, JarvisGoal.status.in_(tuple(_GOAL_ACTIVE)))
                .order_by(JarvisGoal.updated_at.desc())
                .limit(lim)
            ).all()
        )
    for g in goals:
        pending = [s for s in (g.subtasks or []) if (s.status or "").lower() == "pending"]
        if not pending:
            pending = [s for s in (g.subtasks or []) if (s.status or "").lower() not in ("done", "skipped")]
        nxt = min(pending, key=lambda s: int(s.sort_order or 0)) if pending else None
        if nxt:
            out.append(
                {
                    "goal_id": int(g.id),
                    "goal_type": g.goal_type,
                    "description": g.description[:500],
                    "next_subtask_id": int(nxt.id),
                    "next_subtask_title": nxt.title,
                    "organization_id": int(g.organization_id) if g.organization_id else None,
                }
            )
    return out


def get_active_goals_sync(*, user_id: int, limit: int = 20) -> list[dict[str, Any]]:
    uid = int(user_id)
    if uid <= 0:
        return []
    factory = get_session_factory()
    if factory is None:
        return []
    lim = max(1, min(int(limit), 50))
    with factory() as session:
        rows = list(
            session.scalars(
                select(JarvisGoal)
                .options(selectinload(JarvisGoal.subtasks))
                .where(JarvisGoal.user_id == uid, JarvisGoal.status.in_(tuple(_GOAL_ACTIVE)))
                .order_by(JarvisGoal.updated_at.desc())
                .limit(lim)
            ).all()
        )
    res: list[dict[str, Any]] = []
    for g in rows:
        subs = [{"id": int(s.id), "title": s.title, "status": s.status} for s in (g.subtasks or [])]
        res.append(
            {
                "id": int(g.id),
                "goal_type": g.goal_type,
                "description": g.description,
                "target_value": g.target_value,
                "deadline": g.deadline.isoformat() if g.deadline else None,
                "status": g.status,
                "progress": g.progress or {},
                "organization_id": int(g.organization_id) if g.organization_id else None,
                "subtasks": subs,
            }
        )
    return res


def mark_subtask_done_sync(*, goal_id: int, subtask_id: int, user_id: int) -> dict[str, Any]:
    gid, sid, uid = int(goal_id), int(subtask_id), int(user_id)
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "database not configured"}
    with factory() as session:
        with session.begin():
            goal = session.get(JarvisGoal, gid)
            if goal is None or int(goal.user_id) != uid:
                return {"ok": False, "error": "goal not found"}
            st = session.get(JarvisGoalSubtask, sid)
            if st is None or int(st.goal_id) != gid:
                return {"ok": False, "error": "subtask not found"}
            st.status = "done"
    return track_progress_sync(goal_id=gid, user_id=uid)


def resolve_goal_conflicts(goals: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Step 2 — rank goals by urgency, financial impact signal, and dependency/progress shape.

    Returns the **best** goal to act on now plus a ranked list (highest score first).
    """
    if not goals:
        return {"ok": False, "error": "no goals", "best": None, "ranked": [], "scores": []}
    today = date.today()
    scored: list[tuple[float, dict[str, Any]]] = []
    for g in goals:
        if not isinstance(g, dict):
            continue
        desc = (g.get("description") or "").lower()
        urg = 0.5
        if g.get("deadline"):
            try:
                dl_s = str(g.get("deadline"))[:10]
                dl = date.fromisoformat(dl_s)
                days = (dl - today).days
                if days <= 3:
                    urg = 0.95
                elif days <= 14:
                    urg = 0.78
                elif days > 90:
                    urg = 0.28
            except Exception:
                pass
        fin = 0.42
        tv = g.get("target_value")
        if tv:
            try:
                raw = float(str(tv).replace(",", "").split()[0])
                fin = min(1.0, max(0.2, raw / 75000.0))
            except Exception:
                fin = 0.55
        if "profit" in desc or "revenue" in desc or (g.get("goal_type") == "revenue"):
            fin = min(1.0, fin + 0.18)
        dep = 0.48
        prog = g.get("progress") if isinstance(g.get("progress"), dict) else {}
        pct = float(prog.get("percent") or 0)
        if 0 < pct < 70:
            dep = 0.72
        subs = g.get("subtasks") or []
        if isinstance(subs, list):
            pending = sum(1 for s in subs if isinstance(s, dict) and (s.get("status") or "").lower() == "pending")
            if pending >= 3:
                dep = min(1.0, dep + 0.12)
        score = 0.45 * urg + 0.38 * fin + 0.17 * min(1.0, dep)
        scored.append((score, g))
    scored.sort(key=lambda x: -x[0])
    best = scored[0][1] if scored else None
    return {
        "ok": True,
        "best": best,
        "ranked": [x[1] for x in scored[:16]],
        "scores": [round(x[0], 4) for x in scored[:16]],
    }


def create_goal(user_id: int, description: str, **kwargs: Any) -> dict[str, Any]:
    """Public alias matching the Upgrade 2.2 spec name."""
    return create_goal_sync(user_id=int(user_id), description=str(description), **kwargs)


def break_into_subtasks(goal_id: int, user_id: int) -> dict[str, Any]:
    return break_into_subtasks_sync(goal_id=int(goal_id), user_id=int(user_id))


def track_progress(goal_id: int, user_id: int) -> dict[str, Any]:
    return track_progress_sync(goal_id=int(goal_id), user_id=int(user_id))


def auto_continue_incomplete_goals(user_id: int) -> list[dict[str, Any]]:
    return auto_continue_incomplete_goals_sync(user_id=int(user_id))
