"""
Long-horizon strategic planning from active goals (months / weeks / daily actions).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import JarvisGoal
from services.agent_identity_continuity_engine import (
    get_agent_profile,
    mission_alignment_score,
    run_continuity_review,
)
from services.jarvis_goal_engine import get_active_goals_sync
from services.meta_autonomy_engine import generate_self_improvement_tasks


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _horizon(deadline_iso: str | None) -> str:
    if not deadline_iso:
        return "mid_term"
    try:
        d = date.fromisoformat(str(deadline_iso)[:10])
    except ValueError:
        return "mid_term"
    days = (d - date.today()).days
    if days > 56:
        return "long_term"
    if days > 14:
        return "mid_term"
    return "short_term"


def _safe_pct(v: Any) -> float:
    try:
        return max(0.0, min(100.0, float(v)))
    except Exception:
        return 0.0


def _goal_progress_snapshot(goal: dict[str, Any]) -> dict[str, Any]:
    prog = goal.get("progress") if isinstance(goal.get("progress"), dict) else {}
    pct = _safe_pct(prog.get("percent"))
    target = 100.0
    gap = max(0.0, target - pct)
    return {
        "goal_id": int(goal.get("id") or 0),
        "status": str(goal.get("status") or ""),
        "progress_percent": round(pct, 2),
        "target_percent": target,
        "gap_percent": round(gap, 2),
        "as_of": _now_iso(),
    }


def _checkpoint_bundle(desc: str, horizon: str, gap_percent: float) -> dict[str, Any]:
    if horizon == "long_term":
        checkpoints = [
            {"label": "Month 1 milestone", "target_progress_pct": min(35.0, max(10.0, 100.0 - gap_percent + 20.0))},
            {"label": "Month 2 milestone", "target_progress_pct": min(70.0, max(35.0, 100.0 - gap_percent + 45.0))},
            {"label": "Month 3 milestone", "target_progress_pct": 100.0},
        ]
        expected = f"By quarter horizon, '{desc[:120]}' reaches measurable target completion."
    elif horizon == "mid_term":
        checkpoints = [
            {"label": "Week 1 checkpoint", "target_progress_pct": min(45.0, max(15.0, 100.0 - gap_percent + 25.0))},
            {"label": "Week 2 checkpoint", "target_progress_pct": min(80.0, max(45.0, 100.0 - gap_percent + 55.0))},
            {"label": "Week 3 checkpoint", "target_progress_pct": 100.0},
        ]
        expected = f"Within weekly horizon, '{desc[:120]}' should clear current blockers and close gap."
    else:
        checkpoints = [
            {"label": "Today checkpoint", "target_progress_pct": min(75.0, max(20.0, 100.0 - gap_percent + 35.0))},
            {"label": "Next checkpoint", "target_progress_pct": 100.0},
        ]
        expected = f"Short horizon execution should produce immediate progress on '{desc[:120]}'."
    abort_conditions = [
        "governor_disallow_execute",
        "kill_switch_enabled",
        "risk_spike_detected",
        "checkpoint_missed_twice",
    ]
    return {
        "checkpoints": checkpoints,
        "abort_conditions": abort_conditions,
        "expected_outcome": expected,
    }


def build_strategic_goal_plan(
    *,
    user_id: int,
    organization_id: int,
    max_goals: int = 24,
) -> dict[str, Any]:
    agent_profile = get_agent_profile(user_id=int(user_id), organization_id=int(organization_id))
    continuity = run_continuity_review(user_id=int(user_id), organization_id=int(organization_id))
    goals = get_active_goals_sync(user_id=int(user_id), limit=max(1, min(int(max_goals), 60)))
    long_term: list[dict[str, Any]] = []
    mid_term: list[dict[str, Any]] = []
    short_term: list[dict[str, Any]] = []
    progress_vs_plan: list[dict[str, Any]] = []
    for g in goals:
        if not isinstance(g, dict):
            continue
        gid = int(g.get("id") or 0)
        if gid <= 0:
            continue
        desc = str(g.get("description") or "")[:500]
        hor = _horizon(g.get("deadline"))
        prog = _goal_progress_snapshot(g)
        progress_vs_plan.append({**prog, "horizon": hor})
        base = {
            "goal_id": gid,
            "description": desc,
            "deadline": g.get("deadline"),
            "goal_type": str(g.get("goal_type") or "custom"),
            "progress_percent": prog["progress_percent"],
            "gap_percent": prog["gap_percent"],
            "long_term_vision_link": str(agent_profile.get("long_term_vision") or "")[:400],
            "mission_alignment": mission_alignment_score(desc, agent_profile),
        }
        if hor == "long_term":
            cb = _checkpoint_bundle(desc, hor, prog["gap_percent"])
            long_term.append(
                {
                    **base,
                    "plan_note": "Monthly horizon: define milestones and derisk dependencies.",
                    "suggested_monthly_focus": f"Advance '{desc[:120]}' via one major milestone this month.",
                    "checkpoints": cb["checkpoints"],
                    "abort_conditions": cb["abort_conditions"],
                    "expected_outcome": cb["expected_outcome"],
                }
            )
            mid_term.append(
                {
                    **base,
                    "plan_note": "Weekly bridge from long-term milestone.",
                    "suggested_weekly_focus": f"Break '{desc[:120]}' into this week's measurable checkpoint.",
                    "checkpoints": cb["checkpoints"][:2],
                    "abort_conditions": cb["abort_conditions"],
                    "expected_outcome": "Weekly checkpoint continuity for long-horizon objective.",
                }
            )
            short_term.append(
                {
                    **base,
                    "action": f"Today: execute one concrete subtask for '{desc[:160]}' and log outcome.",
                    "priority_0_1": round(min(0.95, 0.55 + (prog["gap_percent"] / 200.0)), 3),
                    "checkpoints": cb["checkpoints"][:1],
                    "abort_conditions": cb["abort_conditions"],
                    "expected_outcome": "Daily progress update with validated outcome evidence.",
                }
            )
        elif hor == "mid_term":
            cb = _checkpoint_bundle(desc, hor, prog["gap_percent"])
            mid_term.append(
                {
                    **base,
                    "plan_note": "Weekly horizon: sequence tasks to hit deadline safely.",
                    "suggested_weekly_focus": f"Complete this week's top blocker for '{desc[:120]}'.",
                    "checkpoints": cb["checkpoints"],
                    "abort_conditions": cb["abort_conditions"],
                    "expected_outcome": cb["expected_outcome"],
                }
            )
            short_term.append(
                {
                    **base,
                    "action": f"Today: complete one step that moves '{desc[:160]}' forward this week.",
                    "priority_0_1": round(min(0.98, 0.62 + (prog["gap_percent"] / 180.0)), 3),
                    "checkpoints": cb["checkpoints"][:1],
                    "abort_conditions": cb["abort_conditions"],
                    "expected_outcome": "Single-day execution artifact advancing weekly goal.",
                }
            )
        else:
            cb = _checkpoint_bundle(desc, hor, prog["gap_percent"])
            short_term.append(
                {
                    **base,
                    "action": f"Today: focus immediate execution for '{desc[:180]}' to avoid deadline slip.",
                    "priority_0_1": round(min(0.99, 0.72 + (prog["gap_percent"] / 150.0)), 3),
                    "checkpoints": cb["checkpoints"],
                    "abort_conditions": cb["abort_conditions"],
                    "expected_outcome": cb["expected_outcome"],
                }
            )

    si = generate_self_improvement_tasks(user_id=int(user_id), organization_id=int(organization_id))
    for t in list(si.get("tasks") or []):
        if not isinstance(t, dict):
            continue
        row = {
            "goal_id": 0,
            "description": str(t.get("title") or "")[:500],
            "deadline": None,
            "goal_type": "self_improvement",
            "progress_percent": 0.0,
            "gap_percent": 100.0,
            "action": str(t.get("title") or "")[:260],
            "priority_0_1": float(t.get("priority_0_1") or 0.7),
            "meta_autonomy_task": True,
            "why": str(t.get("why") or "")[:300],
            "task_type": str(t.get("task_type") or "self_improvement"),
            "checkpoints": [{"label": "Assist review checkpoint", "target_progress_pct": 25.0}],
            "abort_conditions": ["governor_disallow_execute", "kill_switch_enabled"],
            "expected_outcome": "Reviewed and approved improvement task with measurable safety impact.",
        }
        h = str(t.get("horizon") or "short_term")
        if h == "long_term":
            long_term.append(
                {
                    "goal_id": 0,
                    "description": row["description"],
                    "deadline": None,
                    "goal_type": "self_improvement",
                    "progress_percent": 0.0,
                    "gap_percent": 100.0,
                    "plan_note": "Meta-autonomy long-horizon improvement objective.",
                    "suggested_monthly_focus": row["action"],
                    "meta_autonomy_task": True,
                    "checkpoints": [
                        {"label": "Month 1 assist checkpoint", "target_progress_pct": 30.0},
                        {"label": "Month 2 assist checkpoint", "target_progress_pct": 65.0},
                        {"label": "Month 3 assist checkpoint", "target_progress_pct": 100.0},
                    ],
                    "abort_conditions": row["abort_conditions"],
                    "expected_outcome": "Long-horizon improvement program approved and tracked with guardrails.",
                }
            )
        elif h == "mid_term":
            mid_term.append(
                {
                    "goal_id": 0,
                    "description": row["description"],
                    "deadline": None,
                    "goal_type": "self_improvement",
                    "progress_percent": 0.0,
                    "gap_percent": 100.0,
                    "plan_note": "Meta-autonomy mid-term reliability/coverage improvement.",
                    "suggested_weekly_focus": row["action"],
                    "meta_autonomy_task": True,
                    "checkpoints": [
                        {"label": "Week 1 assist checkpoint", "target_progress_pct": 40.0},
                        {"label": "Week 2 assist checkpoint", "target_progress_pct": 75.0},
                        {"label": "Week 3 assist checkpoint", "target_progress_pct": 100.0},
                    ],
                    "abort_conditions": row["abort_conditions"],
                    "expected_outcome": "Mid-term improvement closes key capability/reliability gaps safely.",
                }
            )
        else:
            short_term.append(row)

    short_term.sort(key=lambda x: float(x.get("priority_0_1") or 0.0), reverse=True)
    out = {
        "ok": True,
        "generated_at": _now_iso(),
        "user_id": int(user_id),
        "organization_id": int(organization_id),
        "long_term": long_term[:30],
        "mid_term": mid_term[:40],
        "short_term": short_term[:40],
        "progress_vs_plan": progress_vs_plan[:80],
        "meta_autonomy": si,
        "agent_profile": agent_profile,
        "continuity_review": continuity,
    }
    _persist_goal_plan_snapshot(user_id=int(user_id), organization_id=int(organization_id), plan=out)
    return out


def _persist_goal_plan_snapshot(
    *,
    user_id: int,
    organization_id: int,
    plan: dict[str, Any],
) -> None:
    try:
        factory = get_session_factory()
    except Exception:
        return
    if factory is None:
        return
    with factory() as session:
        agent_profile = (
            plan.get("agent_profile")
            if isinstance(plan.get("agent_profile"), dict)
            else {}
        )
        rows = (
            session.execute(
                select(JarvisGoal).where(
                    JarvisGoal.user_id == int(user_id),
                    JarvisGoal.organization_id == int(organization_id),
                    JarvisGoal.status.in_(("open", "in_progress")),
                )
            )
            .scalars()
            .all()
        )
        progress_map = {
            int(x.get("goal_id") or 0): x
            for x in list(plan.get("progress_vs_plan") or [])
            if isinstance(x, dict)
        }
        for g in rows:
            meta = dict(g.meta or {})
            sg = dict(meta.get("strategic_goal_planner") if isinstance(meta.get("strategic_goal_planner"), dict) else {})
            prog = progress_map.get(int(g.id)) or {}
            sg["last_plan_at"] = str(plan.get("generated_at") or _now_iso())
            sg["horizon"] = str(prog.get("horizon") or _horizon(g.deadline.isoformat() if g.deadline else None))
            sg["progress_percent"] = float(prog.get("progress_percent") or 0.0)
            sg["gap_percent"] = float(prog.get("gap_percent") or 0.0)
            sg["long_term_vision_link"] = str(agent_profile.get("long_term_vision") or "")[:400]
            sg["mission_alignment_required"] = True
            meta["strategic_goal_planner"] = sg
            g.meta = meta
        session.commit()
