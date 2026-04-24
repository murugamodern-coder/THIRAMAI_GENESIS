"""Long-term memory orchestration APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.long_term_memory_engine import (
    evolve_plan_with_memory,
    recall_memories_for_goal,
    store_agent_episode,
    store_strategy_memory,
)

router = APIRouter(tags=["Long-term Memory"])


class MemoryEpisodeBody(BaseModel):
    execution_id: str = Field(..., min_length=1, max_length=128)
    goal_id: int | None = Field(default=None)
    outcome: dict[str, Any] = Field(default_factory=dict)


class MemoryStrategyBody(BaseModel):
    strategy_event: dict[str, Any] = Field(default_factory=dict)


@router.post("/memory/episodes")
async def post_memory_episode(
    body: MemoryEpisodeBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return store_agent_episode(
        user_id=int(user.id),
        execution_id=str(body.execution_id),
        goal_id=body.goal_id,
        outcome=body.outcome or {},
    )


@router.post("/memory/strategies")
async def post_memory_strategy(
    body: MemoryStrategyBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return store_strategy_memory(user_id=int(user.id), strategy_event=body.strategy_event or {})


@router.get("/memory/recall")
async def get_memory_recall(
    q: str = "",
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return recall_memories_for_goal(user_id=int(user.id), goal_context={"description": str(q or "")})


@router.post("/memory/evolve-plan/{goal_id}")
async def post_memory_evolve(
    goal_id: int,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return evolve_plan_with_memory(user_id=int(user.id), goal_id=int(goal_id), goal_context={"goal": f"goal_{goal_id}"})
