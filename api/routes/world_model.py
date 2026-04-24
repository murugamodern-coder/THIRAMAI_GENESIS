"""World model APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from api.dependencies import CurrentUser, require_permission
from services.brain_execute import brain_execute
from services.world_model_engine import get_world_model

router = APIRouter(tags=["World Model"])


@router.get("/world-model/context")
async def get_world_model_context(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return get_world_model(int(user.id))


@router.post("/world-model/refresh")
async def post_world_model_refresh(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return brain_execute(
        "Refresh world model context",
        int(user.id),
        int(user.organization_id),
    )
