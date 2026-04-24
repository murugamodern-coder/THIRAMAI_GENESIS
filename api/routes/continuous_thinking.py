"""Continuous thinking loop APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from api.dependencies import CurrentUser, require_permission
from services.autonomy_contract_engine import autonomy_heartbeat
from services.brain_execute import brain_execute

router = APIRouter(tags=["Continuous Thinking Loop"])


@router.post("/autonomy/continuous/run")
async def post_continuous_run(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return brain_execute(
        "Run continuous thinking cycle",
        int(user.id),
        int(user.organization_id),
    )


@router.get("/autonomy/continuous/status")
async def get_continuous_status(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return {"ok": True, "heartbeat": autonomy_heartbeat(int(user.id))}
