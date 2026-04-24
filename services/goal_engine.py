"""Autonomous goal engine wrapper: context -> goals -> sub-goals -> progress."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.jarvis_goal_engine import (
    break_into_subtasks_sync,
    create_goal_sync,
    get_active_goals_sync,
    mark_subtask_done_sync,
    track_progress_sync,
)
from services.execute_mission_store import create_mission_plan
from services.long_term_memory_engine import evolve_plan_with_memory, recall_memories_for_goal
from services.learning_engine import analyze_patterns
from services.predictive_engine import prediction_summary
from services.simulation_engine import choose_best_simulated_path
from services.world_model_engine import get_world_model


def _now() -> datetime:
    return datetime.now(timezone.utc)


def derive_goals_from_context(user_id: int, organization_id: int) -> dict[str, Any]:
    world = get_world_model(int(user_id))
    pred = prediction_summary(int(user_id))
    insights = analyze_patterns(int(user_id), limit=80)
    trend = str(((pred.get("profit_trend") or {}).get("trend")) or "neutral")
    risk = str(((pred.get("predicted_risk") or {}).get("risk_level")) or "medium")
    recommendations = insights.get("recommendations") or []
    goal_templates: list[str] = []
    if trend == "up" and risk != "high":
        goal_templates.append("Scale high-confidence opportunities while preserving diversification")
    if risk == "high":
        goal_templates.append("Reduce downside exposure and tighten guardrails this week")
    if recommendations:
        goal_templates.append(str(recommendations[0]))
    if not goal_templates:
        goal_templates.append("Improve weekly execution consistency and decision quality")
    created: list[dict[str, Any]] = []
    for desc in goal_templates[:2]:
        out = create_goal_sync(
            user_id=int(user_id),
            organization_id=int(organization_id),
            description=desc,
            goal_type="autonomous",
            meta={"created_by": "goal_engine", "created_at": _now().isoformat()},
        )
        if out.get("ok"):
            gid = int(out.get("goal_id") or 0)
            if gid > 0:
                break_into_subtasks_sync(goal_id=gid, user_id=int(user_id))
                created.append({"goal_id": gid, "description": desc})
    return {"ok": True, "created": created, "world_model": world}


def decompose_goal(goal_id: int, user_id: int) -> dict[str, Any]:
    out = break_into_subtasks_sync(goal_id=int(goal_id), user_id=int(user_id))
    prog = track_progress_sync(goal_id=int(goal_id), user_id=int(user_id))
    memory = recall_memories_for_goal(user_id=int(user_id), goal_context={"goal": f"goal_{goal_id}"})
    evolve = evolve_plan_with_memory(user_id=int(user_id), goal_id=int(goal_id), goal_context={"goal": f"goal_{goal_id}"})
    return {"ok": bool(out.get("ok")), "decomposition": out, "progress": prog, "memory": memory, "evolve": evolve}


def advance_goal_cycle(goal_id: int, user_id: int) -> dict[str, Any]:
    goals = get_active_goals_sync(user_id=int(user_id), limit=40)
    goal = next((g for g in goals if int(g.get("id") or 0) == int(goal_id)), None)
    if not goal:
        return {"ok": False, "error": "Goal not found or inactive"}
    subtasks = goal.get("subtasks") or []
    pending = [s for s in subtasks if str(s.get("status") or "").lower() in {"pending", "in_progress"}]
    if pending:
        first = pending[0]
        sim = choose_best_simulated_path(
            int(user_id),
            {"goal_id": int(goal_id), "subtask_id": int(first.get("id") or 0), "expected_profit": 5000.0},
        )
        if float(((sim.get("chosen_path") or {}).get("success_probability") or 0) < 0.3):
            prog = track_progress_sync(goal_id=int(goal_id), user_id=int(user_id))
            return {"ok": True, "goal_id": int(goal_id), "progress": prog, "skipped": True, "simulation": sim}
        mission = create_mission_plan(user_id=int(user_id), command=str(first.get("title") or "goal subtask execution"))
        mark_subtask_done_sync(
            goal_id=int(goal_id),
            subtask_id=int(first.get("id") or 0),
            user_id=int(user_id),
        )
    else:
        mission = None
    prog = track_progress_sync(goal_id=int(goal_id), user_id=int(user_id))
    return {"ok": True, "goal_id": int(goal_id), "progress": prog, "mission": mission}


def goal_progress_snapshot(user_id: int, horizon: str = "week") -> dict[str, Any]:
    goals = get_active_goals_sync(user_id=int(user_id), limit=60)
    items = []
    for g in goals:
        p = g.get("progress") if isinstance(g.get("progress"), dict) else {}
        items.append(
            {
                "goal_id": int(g.get("id") or 0),
                "description": str(g.get("description") or ""),
                "status": str(g.get("status") or ""),
                "progress_pct": float(p.get("percent") or 0),
                "done_subtasks": int(p.get("done_subtasks") or 0),
                "total_subtasks": int(p.get("total_subtasks") or 0),
            }
        )
    avg = sum(float(i.get("progress_pct") or 0) for i in items) / max(len(items), 1) if items else 0.0
    return {
        "ok": True,
        "horizon": str(horizon or "week"),
        "generated_at": _now().isoformat(),
        "items": items,
        "summary": {"active_goals": len(items), "avg_progress_pct": round(avg, 2)},
    }
