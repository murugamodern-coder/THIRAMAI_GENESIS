"""
Upgrade 2.3 — narrative briefing (Captain-style copy) + clustered critical insights.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from core.database import get_session_factory
from core.db.models import JarvisAgentActionLog, JarvisDailyAgentPlan


def cluster_critical_insights_sync(
    insights: list[dict[str, Any]],
    *,
    max_clusters: int = 6,
    top_n: int = 3,
) -> dict[str, Any]:
    """
    Step 6 — bucket by coarse category from title/recommended_action; keep highest-urgency per bucket.

    Returns ``clusters`` and ``top_critical`` (at most ``top_n``).
    """
    buckets: dict[str, dict[str, Any]] = {}
    for ins in insights:
        if not isinstance(ins, dict):
            continue
        title = str(ins.get("title") or "")
        ra = str(ins.get("recommended_action") or "")
        blob = f"{title} {ra}".lower()
        cat = "general"
        if any(x in blob for x in ("stock", "reorder", "inventory", "sku", "supplier")):
            cat = "inventory"
        elif any(x in blob for x in ("emi", "payment", "invoice", "due", "cash")):
            cat = "cash"
        elif any(x in blob for x in ("equity", "market", "watchlist", "trade", "signal")):
            cat = "market"
        elif any(x in blob for x in ("meet", "calendar")):
            cat = "calendar"
        imp = ins.get("impact") if isinstance(ins.get("impact"), dict) else {}
        urg = float(imp.get("urgency_score") or 0)
        if cat not in buckets or urg > float(buckets[cat].get("_urg", 0)):
            ins2 = dict(ins)
            ins2["_urg"] = urg
            buckets[cat] = ins2
        if len(buckets) >= max_clusters:
            break
    ranked = sorted(buckets.values(), key=lambda x: -float(x.get("_urg", 0)))
    for r in ranked:
        r.pop("_urg", None)
    top = ranked[: max(1, min(int(top_n), 5))]
    return {"clusters": list(buckets.keys()), "representatives": ranked, "top_critical": top}


def build_captain_narrative_sync(*, user_id: int) -> dict[str, Any]:
    """
    Step 5 — human partner tone: yesterday signal + today's focus + optional ``Z`` outcome framing.

    Uses clustered insights (top 3) and today's stored plan when present.
    """
    uid = int(user_id)
    if uid <= 0:
        return {"ok": False, "error": "user_id required"}
    from services.jarvis_autonomous_agent import get_cached_proactive_insights_sync
    from services.jarvis_weekly_strategy import generate_weekly_strategy_sync
    from services.jarvis_world_simulation import simulate_future_state

    insights = get_cached_proactive_insights_sync(user_id=uid)
    pack = cluster_critical_insights_sync(insights, top_n=3)
    top = pack.get("top_critical") or []
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    wins = 0
    fails = 0
    factory = get_session_factory()
    if factory is not None:
        start = datetime(yesterday.year, yesterday.month, yesterday.day, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        try:
            with factory() as session:
                wins = int(
                    session.scalar(
                        select(func.count())
                        .select_from(JarvisAgentActionLog)
                        .where(
                            JarvisAgentActionLog.user_id == uid,
                            JarvisAgentActionLog.outcome == "success",
                            JarvisAgentActionLog.created_at >= start,
                            JarvisAgentActionLog.created_at < end,
                        )
                    )
                    or 0
                )
                fails = int(
                    session.scalar(
                        select(func.count())
                        .select_from(JarvisAgentActionLog)
                        .where(
                            JarvisAgentActionLog.user_id == uid,
                            JarvisAgentActionLog.outcome == "failed",
                            JarvisAgentActionLog.created_at >= start,
                            JarvisAgentActionLog.created_at < end,
                        )
                    )
                    or 0
                )
        except Exception:
            pass
    today = datetime.now(timezone.utc).date()
    plan_hint = ""
    if factory is not None:
        try:
            with factory() as session:
                row = session.execute(
                    select(JarvisDailyAgentPlan).where(
                        JarvisDailyAgentPlan.user_id == uid,
                        JarvisDailyAgentPlan.plan_date == today,
                    ).limit(1)
                ).scalar_one_or_none()
            if row and isinstance(row.payload, dict):
                ta = row.payload.get("top_business_actions") or []
                plan_hint = "; ".join(str(x) for x in ta[:2] if x)
        except Exception:
            pass
    focus = str((top[0].get("recommended_action") or top[0].get("title")) if top else "tighten execution on your #1 revenue lever")
    z_action = None
    z_line = ""
    if top:
        ar = top[0].get("action_ready_payload") if isinstance(top[0].get("action_ready_payload"), dict) else {}
        if ar.get("handler") == "create_purchase_order_draft" and ar.get("lines"):
            ln0 = ar["lines"][0] if isinstance(ar["lines"], list) else {}
            z_action = {
                "kind": "reorder",
                "organization_id": ar.get("organization_id"),
                "sku": ln0.get("sku_name"),
                "order_qty": ln0.get("quantity_ordered"),
                "unit_cost": ln0.get("unit_cost_pre_tax"),
            }
            sim = simulate_future_state(z_action, days=7)
            z_line = sim.get("projected_outcome") or ""
    narrative = (
        f"Captain — yesterday the autonomous loop logged {wins} successful move(s) and {fails} miss(es). "
        f"Today your focus should be: {focus}. "
    )
    if plan_hint:
        narrative += f"Your morning plan highlights: {plan_hint}. "
    if z_line:
        narrative += f"If you clear the top reorder draft, {z_line}"
    else:
        narrative += "If you knock out the top clustered alert before noon, you reduce downstream firefighting."
    generate_weekly_strategy_sync(user_id=uid)
    return {"ok": True, "narrative": narrative.strip(), "top_insights": top, "clusters": pack.get("clusters")}
