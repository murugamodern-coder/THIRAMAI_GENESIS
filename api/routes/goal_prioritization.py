"""Goal prioritization APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from api.dependencies import CurrentUser, require_permission
from services.goal_prioritization_engine import prioritize_goals

router = APIRouter(tags=["Goal Prioritization"])


@router.get("/goals/prioritized")
async def get_prioritized_goals(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return prioritize_goals(int(user.id))
