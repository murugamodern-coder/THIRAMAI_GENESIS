"""
Proactive autonomy: self-generated daily work, long-horizon goal view, auto priority, next actions.
Builds on Jarvis goals, daily plan storage, and predictive/world/learning context.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import JarvisDailyAgentPlan, JarvisGoal
from services.agent_identity_continuity_engine import get_agent_profile, mission_alignment_score
from services.autonomy_governor_engine import compute_autonomy_decision
from services.event_listener_engine import detect_realtime_triggers
from services.feedback_engine import calculate_prediction_accuracy
from services.jarvis_goal_engine import (
    auto_continue_incomplete_goals_sync,
    get_active_goals_sync,
    resolve_goal_conflicts,
)
from services.learning_engine import analyze_patterns
from services.meta_autonomy_engine import monitor_system_performance
from services.predictive_engine import prediction_summary
from services.world_model_engine import get_world_model


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _session_ok():
    try:
        return get_session_factory() is not None
    except Exception:
        return None


def _horizon_label(deadline: date | None) -> str:
    if not deadline:
        return "unbounded"
    d = (deadline - date.today()).days
    if d < 0:
        return "overdue"
    if d <= 14:
        return "0-2w"
    if d <= 56:
        return "2-8w"
    if d <= 120:
        return "2-4m"
    if d <= 400:
        return "4-12m"
    return "12m+"


def _env_multiplier(
    goal: dict[str, Any],
    pred: dict[str, Any],
    world: dict[str, Any],
) -> float:
    risk = str(((pred.get("predicted_risk") or {}).get("risk_level")) or "medium")
    trend = str(((pred.get("profit_trend") or {}).get("trend")) or "unknown")
    regime = str(((world.get("market_behavior") or {}).get("regime")) or "balanced")
    gtype = str(goal.get("goal_type") or "custom")
    m = 1.0
    if risk == "high":
        if gtype in ("cost", "finance", "custom"):
            m *= 1.1
        if gtype == "revenue":
            m *= 0.92
    elif risk == "low" and trend == "up" and gtype == "revenue":
        m *= 1.08
    if regime == "defensive" and gtype in ("cost", "finance"):
        m *= 1.06
    if regime == "expansion" and gtype == "revenue":
        m *= 1.05
    return max(0.4, min(1.25, m))


def long_term_goal_tracking(
    user_id: int,
    *,
    max_goals: int = 30,
) -> dict[str, Any]:
    """Weeks/months view over active Jarvis goals (deadline + progress)."""
    goals = get_active_goals_sync(user_id=int(user_id), limit=max(5, int(max_goals)))
    today = date.today()
    items: list[dict[str, Any]] = []
    for g in goals:
        if not isinstance(g, dict):
            continue
        dl: date | None = None
        if g.get("deadline"):
            try:
                dl = date.fromisoformat(str(g.get("deadline"))[:10])
            except ValueError:
                dl = None
        prog = g.get("progress") if isinstance(g.get("progress"), dict) else {}
        wk = 0.0
        if dl:
            wk = max(0.0, (dl - today).days / 7.0)
        items.append(
            {
                "goal_id": int(g.get("id") or 0),
                "description": (g.get("description") or "")[:800],
                "goal_type": g.get("goal_type"),
                "deadline": g.get("deadline"),
                "weeks_to_deadline": round(wk, 1) if dl else None,
                "horizon": _horizon_label(dl),
                "progress_pct": float(prog.get("percent") or 0),
                "proactive_meta": (g.get("meta") or {}).get("proactive_autonomy")
                if isinstance(g.get("meta"), dict)
                else None,
            }
        )
    by_h: dict[str, int] = {}
    for it in items:
        by_h[it["horizon"]] = by_h.get(it["horizon"], 0) + 1
    return {
        "ok": True,
        "generated_at": _now_utc().isoformat(),
        "items": items,
        "by_horizon": by_h,
    }


def _task_id(title: str) -> str:
    h = hashlib.md5(f"{title[:120]}".encode(), usedforsecurity=False).hexdigest()[:8]
    return f"pat_{h}"


def _goal_risk_score(title: str, detail: dict[str, Any] | None = None) -> float:
    txt = f"{title} {detail or {}}".lower()
    high_terms = ("trade", "buy", "sell", "transfer", "contract", "payment", "delete", "deploy")
    medium_terms = ("supplier", "price", "negotiat", "execute", "order")
    score = 25.0
    if any(t in txt for t in medium_terms):
        score += 25.0
    if any(t in txt for t in high_terms):
        score += 35.0
    return max(0.0, min(95.0, score))


def _goal_reversibility(title: str, detail: dict[str, Any] | None = None) -> float:
    txt = f"{title} {detail or {}}".lower()
    if any(k in txt for k in ("delete", "drop", "transfer", "payment", "contract", "deploy")):
        return 0.25
    if any(k in txt for k in ("optimize", "analyze", "discover", "explore", "simulate")):
        return 0.85
    return 0.65


def _goal_type_from_title(title: str) -> str:
    t = str(title or "").lower()
    if any(k in t for k in ("discover", "explore", "scan", "opportunity", "research")):
        return "discover_new_opportunities"
    if any(k in t for k in ("optimize", "improve", "reduce", "stabilize", "efficiency")):
        return "optimize_existing_system"
    if any(k in t for k in ("build", "tool", "capability", "connector", "bridge")):
        return "build_missing_capability"
    return "optimize_existing_system"


def _append_self_directed_goal_candidates(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = list(actions)
    out.extend(
        [
            {
                "kind": "curiosity_goal",
                "title": "Discover new opportunities in underexploited markets",
                "priority": 0.72,
                "detail": {"goal_type": "discover_new_opportunities", "source": "curiosity_driven"},
            },
            {
                "kind": "improvement_goal",
                "title": "Optimize existing system latency and failure recovery",
                "priority": 0.78,
                "detail": {"goal_type": "optimize_existing_system", "source": "improvement_driven"},
            },
            {
                "kind": "capability_goal",
                "title": "Build missing capability through sandboxed tool prototype",
                "priority": 0.70,
                "detail": {"goal_type": "build_missing_capability", "source": "capability_gap"},
            },
        ]
    )
    return out


def generate_controlled_self_goals(
    user_id: int,
    organization_id: int,
    *,
    limit: int = 8,
) -> dict[str, Any]:
    """
    Controlled self-goal generation:
    - mission/identity aligned
    - governor screened
    - high-risk goals never auto-execute
    """
    uid = int(user_id)
    oid = int(organization_id)
    profile = get_agent_profile(user_id=uid, organization_id=oid)
    suggestions = suggest_next_actions(uid, oid, limit=max(4, min(int(limit), 20)))
    actions = [a for a in list(suggestions.get("actions") or []) if isinstance(a, dict)]
    actions = _append_self_directed_goal_candidates(actions)
    trust = float(calculate_prediction_accuracy(uid, limit=220).get("system_trust_score") or 50.0)
    perf = monitor_system_performance(user_id=uid, organization_id=oid, hours=24 * 7)
    failure_rate = float(perf.get("failure_rate") or 0.0)
    events = detect_realtime_triggers(user_id=uid, organization_id=oid)
    proposed: list[dict[str, Any]] = []
    for a in actions:
        title = str(a.get("title") or "").strip()[:260]
        if not title:
            continue
        detail = a.get("detail") if isinstance(a.get("detail"), dict) else {}
        align = mission_alignment_score(title, profile)
        risk = _goal_risk_score(title, detail)
        reversibility = _goal_reversibility(title, detail)
        conf = max(0.05, min(0.99, (float(a.get("priority") or 0.5) * 0.5) + (align * 0.5)))
        gov = compute_autonomy_decision(
            user_id=uid,
            organization_id=oid,
            domain="automation",
            system_trust_score=trust,
            action_risk_score=risk,
            plan_confidence_score=conf,
            recent_failure_rate=failure_rate,
            repeated_failure_rate=0.0,
            style=str(profile.get("style") or "balanced"),
            active_triggers=list(events.get("triggers") or []),
        )
        high_risk = risk >= 75.0
        low_reversible = reversibility < 0.4
        can_auto = bool(gov.get("allow_execute")) and not high_risk and not low_reversible and align >= 0.45
        proposed.append(
            {
                "title": title,
                "source_kind": str(a.get("kind") or ""),
                "goal_type": _goal_type_from_title(title),
                "mission_alignment": round(align, 3),
                "goal_confidence": round(conf, 3),
                "risk_score": round(risk, 2),
                "reversibility": round(reversibility, 3),
                "governor_mode": str(gov.get("mode") or "assist"),
                "can_auto_execute": bool(can_auto),
                "requires_assist": (not can_auto) or high_risk or low_reversible,
                "high_risk_goal": high_risk,
                "governor_reason": str(gov.get("reason") or ""),
            }
        )
    proposed.sort(
        key=lambda x: (
            float(x.get("mission_alignment") or 0.0),
            float(x.get("goal_confidence") or 0.0),
            -float(x.get("risk_score") or 0.0),
        ),
        reverse=True,
    )
    return {
        "ok": True,
        "generated_at": _now_utc().isoformat(),
        "proposed_goals": proposed[: max(1, min(int(limit), 20))],
        "goal_confidence": round(
            sum(float(x.get("goal_confidence") or 0.0) for x in proposed[: max(1, min(int(limit), 20))])
            / max(1, len(proposed[: max(1, min(int(limit), 20))])),
            3,
        )
        if proposed
        else 0.0,
    }


def generate_self_tasks(
    user_id: int,
    organization_id: int,
    *,
    max_tasks: int = 8,
) -> dict[str, Any]:
    """Daily self-generated task list from context + open goal work (not persisted by itself)."""
    pred = prediction_summary(int(user_id))
    world = get_world_model(int(user_id))
    ins = analyze_patterns(int(user_id), limit=100)
    recs = (ins or {}).get("recommendations") or []
    continuations = auto_continue_incomplete_goals_sync(user_id=int(user_id), limit=8)
    tasks: list[dict[str, Any]] = []
    regime = str(((world.get("market_behavior") or {}).get("regime")) or "balanced")
    for r in recs[:2]:
        tasks.append(
            {
                "id": _task_id(str(r)),
                "title": f"Act on: {str(r)[:200]}",
                "reason": "learning_engine_recommendation",
                "priority_0_1": 0.75,
                "source": "learning",
            }
        )
    tasks.append(
        {
            "id": _task_id("regime"),
            "title": f"Alignment check: current regime is «{regime}»—scan one process that still assumes the opposite.",
            "reason": "world_model",
            "priority_0_1": 0.55,
            "source": "world",
        }
    )
    for c in continuations[:3]:
        tasks.append(
            {
                "id": _task_id(str(c.get("next_subtask_title") or "sub")),
                "title": f"Goal follow-up: {str(c.get('next_subtask_title') or 'next step')[:220]}",
                "reason": f"active_goal_{c.get('goal_id')}",
                "priority_0_1": 0.88,
                "source": "goal_subtask",
                "goal_id": c.get("goal_id"),
            }
        )
    risk = str(((pred.get("predicted_risk") or {}).get("risk_level")) or "medium")
    if risk == "high":
        tasks.append(
            {
                "id": _task_id("risk"),
                "title": "Tighten limits: list top 3 exposures and one concrete guardrail to adjust today.",
                "reason": "high_predicted_risk",
                "priority_0_1": 0.9,
                "source": "prediction",
            }
        )
    if str(((pred.get("profit_trend") or {}).get("trend")) or "") == "up":
        tasks.append(
            {
                "id": _task_id("trend"),
                "title": "Select one high-confidence opportunity to move forward (simulation gate if enabled).",
                "reason": "profit_trend_favorable",
                "priority_0_1": 0.7,
                "source": "prediction",
            }
        )
    # dedupe by title
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for t in sorted(tasks, key=lambda x: -float(x.get("priority_0_1") or 0)):
        k = (t.get("title") or "").lower()[:160]
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return {"ok": True, "tasks": out[: max(3, min(16, int(max_tasks)))], "generated_at": _now_utc().isoformat()}


def auto_adjust_goal_priorities(user_id: int) -> dict[str, Any]:
    """
    Rerank open goals with environment multipliers; persist in ``goal.meta.proactive_autonomy``.
    """
    if not _session_ok():
        return {"ok": False, "error": "Database unavailable"}
    goals = get_active_goals_sync(user_id=int(user_id), limit=40)
    if not goals:
        return {"ok": True, "updated": 0, "message": "No active goals"}
    pred = prediction_summary(int(user_id))
    world = get_world_model(int(user_id))
    r = resolve_goal_conflicts([dict(x) for x in goals if isinstance(x, dict)])
    ranked: list[dict[str, Any]] = list((r or {}).get("ranked") or goals)
    scores: list[float] = list((r or {}).get("scores") or [])
    while len(scores) < len(ranked):
        scores.append(0.5)
    adjusted: list[dict[str, Any]] = []
    for i, g in enumerate(ranked):
        if not isinstance(g, dict):
            continue
        base = float(scores[i]) if i < len(scores) else 0.5
        m = _env_multiplier(g, pred, world)
        adj = min(0.99, max(0.02, base * m))
        adjusted.append({**g, "adjusted_score": round(adj, 4), "env_multiplier": round(m, 4), "base_score": round(base, 4)})
    adjusted.sort(key=lambda x: -float(x.get("adjusted_score") or 0))
    factory = get_session_factory()
    n = 0
    with factory() as session:
        with session.begin():
            for rank, item in enumerate(adjusted, start=1):
                gid = int(item.get("id") or 0)
                if gid <= 0:
                    continue
                row = session.get(JarvisGoal, gid)
                if row is None or int(row.user_id) != int(user_id):
                    continue
                mm = row.meta or {}
                if not isinstance(mm, dict):
                    mm = {}
                mm["proactive_autonomy"] = {
                    "rank": int(rank),
                    "priority_score": float(item.get("adjusted_score") or 0),
                    "base_score": float(item.get("base_score") or 0),
                    "env_multiplier": float(item.get("env_multiplier") or 1.0),
                    "as_of": _now_utc().isoformat(),
                }
                row.meta = mm
                row.updated_at = _now_utc()
                n += 1
    return {"ok": True, "updated": n, "ranked": [{"goal_id": int(x.get("id") or 0), "rank": i + 1, "score": x.get("adjusted_score")} for i, x in enumerate(adjusted[:20])]}


def suggest_next_actions(
    user_id: int,
    organization_id: int,
    *,
    limit: int = 7,
) -> dict[str, Any]:
    """Ranked next actions without user input: goals + daily self-tasks + continuations."""
    tgen = generate_self_tasks(int(user_id), int(organization_id), max_tasks=12)
    g_tasks = tgen.get("tasks") or []
    cont = auto_continue_incomplete_goals_sync(user_id=int(user_id), limit=10)
    actions: list[dict[str, Any]] = []
    for t in g_tasks:
        actions.append(
            {
                "kind": "proactive_task",
                "title": t.get("title"),
                "priority": float(t.get("priority_0_1") or 0.5),
                "detail": t,
            }
        )
    for c in cont:
        actions.append(
            {
                "kind": "continue_goal",
                "title": c.get("next_subtask_title"),
                "priority": 0.86,
                "detail": c,
            }
        )
    actions.sort(key=lambda x: -float(x.get("priority") or 0))
    return {
        "ok": True,
        "suggested_at": _now_utc().isoformat(),
        "actions": actions[: max(1, min(20, int(limit)))],
    }


def _cost_value_for_action(action: dict[str, Any]) -> tuple[float, float]:
    title = str(action.get("title") or "").lower()
    detail = action.get("detail") if isinstance(action.get("detail"), dict) else {}
    base_cost = 8.0
    if any(k in title for k in ("deploy", "contract", "trade", "payment")):
        base_cost = 30.0
    elif any(k in title for k in ("notify", "alignment", "check")):
        base_cost = 4.0
    value = 20.0 + (float(action.get("priority") or 0.5) * 80.0)
    if isinstance(detail, dict) and detail.get("goal_id"):
        value += 10.0
    return round(base_cost, 2), round(value, 2)


def global_priority_engine(
    user_id: int,
    organization_id: int,
    *,
    limit: int = 20,
) -> dict[str, Any]:
    """
    Global ranking over goals/tasks/opportunities using mission + ROI + risk + trust.
    """
    uid = int(user_id)
    oid = int(organization_id)
    profile = get_agent_profile(user_id=uid, organization_id=oid)
    trust = float(calculate_prediction_accuracy(uid, limit=220).get("system_trust_score") or 50.0)
    perf = monitor_system_performance(user_id=uid, organization_id=oid, hours=24 * 7)
    failure_rate = float(perf.get("failure_rate") or 0.0)
    nxt = suggest_next_actions(uid, oid, limit=max(8, min(int(limit), 40)))
    rows: list[dict[str, Any]] = []
    for a in list(nxt.get("actions") or []):
        if not isinstance(a, dict):
            continue
        title = str(a.get("title") or "").strip()
        if not title:
            continue
        cost, value = _cost_value_for_action(a)
        roi = (value - cost) / max(1.0, cost)
        mission = mission_alignment_score(title, profile)
        risk = 0.25 if "check" in title.lower() else (0.55 if any(k in title.lower() for k in ("trade", "contract", "payment")) else 0.4)
        trust_factor = max(0.2, min(1.2, trust / 100.0))
        score = (mission * 0.30) + (min(2.0, roi) / 2.0 * 0.30) + ((1.0 - risk) * 0.20) + (trust_factor * 0.20)
        score = score * (1.0 - min(0.6, failure_rate))
        rows.append(
            {
                "title": title[:260],
                "kind": str(a.get("kind") or ""),
                "mission_alignment": round(mission, 3),
                "cost_units": cost,
                "value_units": value,
                "roi": round(roi, 3),
                "risk": round(risk, 3),
                "trust": round(trust, 2),
                "priority_score": round(score, 4),
                "detail": a.get("detail") if isinstance(a.get("detail"), dict) else {},
            }
        )
    rows.sort(key=lambda x: float(x.get("priority_score") or 0.0), reverse=True)
    return {
        "ok": True,
        "generated_at": _now_utc().isoformat(),
        "inputs": {
            "trust_score": round(trust, 2),
            "failure_rate": round(failure_rate, 4),
            "mission": str(profile.get("mission") or "")[:200],
        },
        "ranked": rows[: max(1, min(int(limit), 40))],
    }


def merge_proactive_section_into_daily_plan(
    user_id: int,
    block: dict[str, Any],
) -> dict[str, Any]:
    """Store under today's ``JarvisDailyAgentPlan`` payload as ``proactive_autonomy``."""
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "Database unavailable"}
    today = _now_utc().date()
    uid = int(user_id)
    with factory() as session:
        with session.begin():
            ex = session.execute(
                select(JarvisDailyAgentPlan).where(JarvisDailyAgentPlan.user_id == uid, JarvisDailyAgentPlan.plan_date == today).limit(1)
            ).scalar_one_or_none()
            p = dict(ex.payload or {}) if ex else {}
            p["proactive_autonomy"] = {**block, "written_at": _now_utc().isoformat()}
            if ex:
                ex.payload = p
            else:
                session.add(JarvisDailyAgentPlan(user_id=uid, plan_date=today, payload=p))
    return {"ok": True, "plan_date": str(today)}


def run_proactive_autonomy_cycle(
    user_id: int,
    organization_id: int,
    *,
    persist_daily: bool = True,
    adjust_priorities: bool = True,
) -> dict[str, Any]:
    """End-to-end: self tasks, long-term view, optional priority update, next actions, optional daily plan merge."""
    daily = generate_self_tasks(int(user_id), int(organization_id))
    horiz = long_term_goal_tracking(int(user_id))
    pri: dict[str, Any] = {"ok": True, "skipped": True}
    if adjust_priorities:
        pri = auto_adjust_goal_priorities(int(user_id))
    nxt = suggest_next_actions(int(user_id), int(organization_id), limit=10)
    gpe = global_priority_engine(int(user_id), int(organization_id), limit=20)
    out = {
        "ok": True,
        "cycled_at": _now_utc().isoformat(),
        "self_generated_tasks": daily,
        "long_term_goals": horiz,
        "priority_update": pri,
        "next_actions": nxt,
        "global_priority": gpe,
    }
    if persist_daily and daily.get("ok"):
        merge_proactive_section_into_daily_plan(
            int(user_id),
            {
                "self_tasks": daily.get("tasks") or [],
                "next_action_titles": [a.get("title") for a in (nxt.get("actions") or [])[:5]],
            },
        )
    return out


def get_todays_proactive_block(user_id: int) -> dict[str, Any]:
    """Read merged proactive section for today (if any)."""
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "Database unavailable"}
    today = _now_utc().date()
    with factory() as session:
        ex = session.execute(
            select(JarvisDailyAgentPlan).where(JarvisDailyAgentPlan.user_id == int(user_id), JarvisDailyAgentPlan.plan_date == today).limit(1)
        ).scalar_one_or_none()
        if not ex:
            return {"ok": True, "plan_date": str(today), "proactive_autonomy": None}
        p = (ex.payload or {}) if ex else {}
        return {"ok": True, "plan_date": str(today), "proactive_autonomy": p.get("proactive_autonomy"), "full_payload": p}
