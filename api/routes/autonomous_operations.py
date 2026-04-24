"""Autonomous operations APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from api.dependencies import CurrentUser, require_permission
from services.brain_execute import brain_execute

router = APIRouter(tags=["Autonomous Operations"])


@router.post("/operations/daily-cycle")
async def post_operations_daily_cycle(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return brain_execute(
        "Run daily autonomous operations cycle",
        int(user.id),
        int(user.organization_id),
    )


@router.post("/operations/daily-cycle/all")
async def post_operations_daily_cycle_all(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return brain_execute(
        "Run multi-organization daily autonomous operations cycle",
        int(user.id),
        int(user.organization_id),
    )
