"""Long-term memory orchestrator over existing Jarvis memory primitives."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.jarvis_memory_engine import get_default_engine


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def store_agent_episode(
    *,
    user_id: int,
    execution_id: str,
    goal_id: int | None,
    outcome: dict[str, Any] | None,
) -> dict[str, Any]:
    eng = get_default_engine()
    content = {
        "execution_id": str(execution_id or ""),
        "goal_id": int(goal_id) if goal_id else None,
        "outcome": outcome or {},
        "stored_at": _now_iso(),
    }
    return eng.store_episode(
        int(user_id),
        "agent_execution",
        content=str(content),
        importance=7,
        title=f"Execution {execution_id}",
    )


def store_strategy_memory(*, user_id: int, strategy_event: dict[str, Any]) -> dict[str, Any]:
    eng = get_default_engine()
    strategy = str((strategy_event or {}).get("strategy") or "general")
    event = str(strategy_event or {})
    return eng.store_fact(
        int(user_id),
        "strategy",
        key=f"last_event:{strategy}",
        value=event[:1500],
        source="long_term_memory_engine",
        confidence=0.7,
    )


def recall_memories_for_goal(*, user_id: int, goal_context: dict[str, Any]) -> dict[str, Any]:
    eng = get_default_engine()
    q = str((goal_context or {}).get("description") or (goal_context or {}).get("goal") or "").strip()
    recalled = eng.recall(int(user_id), q, top_k=8) if q else []
    return {"ok": True, "query": q, "items": recalled}


def evolve_plan_with_memory(*, user_id: int, goal_id: int, goal_context: dict[str, Any] | None = None) -> dict[str, Any]:
    memory = recall_memories_for_goal(user_id=int(user_id), goal_context=goal_context or {"goal": f"goal:{goal_id}"})
    insights = []
    for item in memory.get("items") or []:
        summary = str(item.get("summary") or "")
        if summary:
            insights.append(summary[:220])
    suggestions = []
    if insights:
        suggestions.append("Reuse previously successful sequence for similar goals.")
    if len(insights) >= 3:
        suggestions.append("Increase priority on actions that appear in top recalled episodes.")
    if not suggestions:
        suggestions.append("Collect more episodes for this goal domain.")
    return {"ok": True, "goal_id": int(goal_id), "memory_insights": insights[:6], "plan_adjustments": suggestions}
