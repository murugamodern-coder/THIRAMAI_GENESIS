"""Central execution API: detect intent -> route -> execute."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.central_execution_engine import ExecutionContext, execute_command

router = APIRouter(tags=["Central Execution"])


class ExecuteRequest(BaseModel):
    command: str = Field(..., min_length=3, max_length=4000)


class ExecuteResponse(BaseModel):
    intent: str
    steps: list[str]
    result: Any
    status: str


_INTENT_PERMISSION = {
    "research": "run_research",
    "business": "manage_business",
    "personal": "view_personal",
    "trading": "trade_stock",
    "build": "build_apps",
}


@router.post(
    "/execute",
    response_model=ExecuteResponse,
    summary="Central execution API for Thiramai",
)
async def post_execute(
    body: ExecuteRequest,
    user: CurrentUser = Depends(require_permission("build_apps", "run_research", "manage_business", "view_personal", "trade_stock")),
) -> ExecuteResponse:
    ctx = ExecutionContext(
        user_id=int(user.id),
        organization_id=int(user.organization_id),
        role_name=user.role_name,
    )
    out = execute_command(body.command, ctx)

    need_perm = _INTENT_PERMISSION.get(out.get("intent") or "")
    if need_perm:
        checker = require_permission(need_perm)
        # Validate intent-level permission explicitly so "build_apps" can call endpoint but not cross-domain execute.
        await checker(user)

    status = str(out.get("status") or "error")
    if status not in {"success", "error"}:
        raise HTTPException(status_code=500, detail="Invalid execution status")
    return ExecuteResponse(**out)
