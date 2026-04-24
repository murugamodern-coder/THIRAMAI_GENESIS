"""Proactive autonomy: daily self-tasks, long-horizon goals, auto priorities, next actions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.proactive_autonomy_engine import (
    auto_adjust_goal_priorities,
    generate_self_tasks,
    get_todays_proactive_block,
    long_term_goal_tracking,
    run_proactive_autonomy_cycle,
    suggest_next_actions,
)

router = APIRouter(tags=["Proactive autonomy"])


class ProactiveCycleBody(BaseModel):
    persist_daily: bool = True
    adjust_priorities: bool = True


@router.get("/proactive-autonomy/self-tasks")
async def get_proactive_self_tasks(
    max_tasks: int = Query(8, ge=3, le=16),
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return generate_self_tasks(int(user.id), int(user.organization_id), max_tasks=int(max_tasks))


@router.get("/proactive-autonomy/goal-horizons")
async def get_proactive_goal_horizons(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return long_term_goal_tracking(int(user.id))


@router.post("/proactive-autonomy/adjust-priorities")
async def post_proactive_adjust_priorities(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return auto_adjust_goal_priorities(int(user.id))


@router.get("/proactive-autonomy/next-actions")
async def get_proactive_next_actions(
    limit: int = Query(7, ge=1, le=20),
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return suggest_next_actions(int(user.id), int(user.organization_id), limit=int(limit))


@router.get("/proactive-autonomy/daily")
async def get_proactive_daily_block(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return get_todays_proactive_block(int(user.id))


@router.post("/proactive-autonomy/cycle")
async def post_proactive_cycle(
    body: ProactiveCycleBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return run_proactive_autonomy_cycle(
        int(user.id),
        int(user.organization_id),
        persist_daily=body.persist_daily,
        adjust_priorities=body.adjust_priorities,
    )
