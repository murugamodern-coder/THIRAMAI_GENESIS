"""
Upgrade 2.3 — weekly strategic layer: focus, risks, growth (persisted as ``JarvisFact``).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import JarvisFact


def _iso_week_key(today: date | None = None) -> str:
    d = today or date.today()
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def generate_weekly_strategy_sync(*, user_id: int) -> dict[str, Any]:
    """
    Step 4 — derive focus / risk / growth suggestions from goals + recent agentic insights.

    Stored under ``JarvisFact`` ``fact_type=weekly_strategy`` for recall in narrative.
    """
    uid = int(user_id)
    if uid <= 0:
        return {"ok": False, "error": "user_id required"}
    from services.jarvis_goal_engine import get_active_goals_sync, resolve_goal_conflicts
    from services.jarvis_autonomous_agent import get_cached_proactive_insights_sync

    goals = get_active_goals_sync(user_id=uid, limit=12)
    resolution = resolve_goal_conflicts(goals)
    best = resolution.get("best") if isinstance(resolution, dict) else None
    insights = get_cached_proactive_insights_sync(user_id=uid)
    risk_titles = [str(x.get("title") or "") for x in insights if float(x.get("impact", {}).get("urgency_score") or 0) > 0.82][:5]
    body: dict[str, Any] = {
        "week": _iso_week_key(),
        "focus_areas": [],
        "risk_areas": risk_titles or ["Liquidity and receivables discipline"],
        "growth_suggestions": [],
        "best_goal_id": (best or {}).get("id") if isinstance(best, dict) else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if isinstance(best, dict) and best.get("description"):
        body["focus_areas"].append(str(best.get("description"))[:400])
    for g in goals[:3]:
        if isinstance(g, dict) and g.get("goal_type") == "revenue":
            body["growth_suggestions"].append("Run one pricing experiment on your top SKU this week.")
            break
    if not body["growth_suggestions"]:
        body["growth_suggestions"].append("Block 2h for customer follow-ups; refresh top-5 receivables list.")
    factory = get_session_factory()
    if factory is not None:
        key = _iso_week_key()
        blob = json.dumps(body)[:12000]
        now = datetime.now(timezone.utc)
        try:
            with factory() as session:
                with session.begin():
                    row = session.execute(
                        select(JarvisFact).where(
                            JarvisFact.user_id == uid,
                            JarvisFact.fact_type == "weekly_strategy",
                            JarvisFact.key == key,
                        ).limit(1)
                    ).scalar_one_or_none()
                    if row:
                        r2 = session.get(JarvisFact, row.id)
                        if r2:
                            r2.value = blob
                            r2.last_verified = now
                    else:
                        session.add(
                            JarvisFact(
                                user_id=uid,
                                fact_type="weekly_strategy",
                                key=key,
                                value=blob,
                                confidence=0.62,
                                source="jarvis_weekly_strategy",
                                last_verified=now,
                            )
                        )
        except Exception:
            pass
    return {"ok": True, "strategy": body}
