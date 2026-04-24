"""Goal Engine APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.goal_engine import advance_goal_cycle, decompose_goal, derive_goals_from_context, goal_progress_snapshot

router = APIRouter(tags=["Goal Engine"])


class GoalCycleBody(BaseModel):
    goal_id: int = Field(..., ge=1)


@router.post("/goals/autocreate")
async def post_goals_autocreate(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return derive_goals_from_context(int(user.id), int(user.organization_id))


@router.post("/goals/{goal_id}/decompose")
async def post_goal_decompose(
    goal_id: int,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return decompose_goal(int(goal_id), int(user.id))


@router.post("/goals/{goal_id}/cycle")
async def post_goal_cycle(
    goal_id: int,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return advance_goal_cycle(int(goal_id), int(user.id))


@router.get("/goals/progress")
async def get_goals_progress(
    horizon: str = "week",
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return goal_progress_snapshot(int(user.id), horizon=str(horizon or "week"))
