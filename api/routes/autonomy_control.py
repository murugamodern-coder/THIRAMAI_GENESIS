"""Autonomy mode/state APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.autonomy_contract_engine import autonomy_heartbeat, get_autonomy_state, set_autonomy_state

router = APIRouter(tags=["Autonomy Control"])


class AutonomyModeBody(BaseModel):
    mode: str = Field("recommend", max_length=32)
    approval_required_for_high_impact: bool = Field(True)
    notes: str = Field("", max_length=500)


@router.get("/autonomy/state")
async def get_autonomy_mode(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "build_apps", "run_research")),
) -> dict[str, Any]:
    return get_autonomy_state(int(user.id))


@router.post("/autonomy/state")
async def post_autonomy_mode(
    body: AutonomyModeBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "build_apps", "run_research")),
) -> dict[str, Any]:
    return set_autonomy_state(
        user_id=int(user.id),
        organization_id=int(user.organization_id),
        mode=body.mode,
        approval_required_for_high_impact=bool(body.approval_required_for_high_impact),
        notes=body.notes,
    )


@router.get("/autonomy/heartbeat")
async def get_autonomy_heartbeat(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "build_apps", "run_research")),
) -> dict[str, Any]:
    return autonomy_heartbeat(int(user.id))
