"""Learning insights and strategy profile APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from api.dependencies import CurrentUser, require_permission
from services.learning_engine import analyze_patterns, get_strategy_profiles, update_strategy_profiles
from services.async_task_queue import enqueue_task
from services.feedback_engine import calculate_prediction_accuracy

router = APIRouter(tags=["Learning"])


@router.get("/learning/insights")
async def get_learning_insights(
    limit: int = Query(120, ge=20, le=1000),
    refresh: bool = Query(False),
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    if refresh:
        queued = enqueue_task("learning_optimize", {"user_id": int(user.id)})
        if not queued.get("queued"):
            update_strategy_profiles(int(user.id))
    insights = analyze_patterns(user_id=int(user.id), limit=limit)
    insights["feedback_accuracy"] = calculate_prediction_accuracy(int(user.id), limit=220)
    return insights


@router.get("/learning/strategies")
async def get_learning_strategies(
    refresh: bool = Query(False),
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    if refresh:
        queued = enqueue_task("learning_optimize", {"user_id": int(user.id)})
        if not queued.get("queued"):
            update_strategy_profiles(int(user.id))
    return {"ok": True, "items": get_strategy_profiles(int(user.id))}
