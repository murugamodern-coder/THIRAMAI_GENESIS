"""Unified execution entry: intent → plan → ``execute_action_plan`` (single path)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.brain_execute import brain_execute

router = APIRouter(tags=["Brain execute"])


class BrainExecuteRequest(BaseModel):
    command: str = Field(..., min_length=1, max_length=8000)
    user_id: int = Field(..., ge=1)
    organization_id: int = Field(..., ge=1)


@router.post("/brain/execute")
async def post_brain_execute(
    body: BrainExecuteRequest,
    user: CurrentUser = Depends(
        require_permission("build_apps", "run_research", "manage_business", "view_personal", "trade_stock")
    ),
) -> dict[str, Any]:
    if int(body.user_id) != int(user.id) or int(body.organization_id) != int(user.organization_id):
        raise HTTPException(
            status_code=403,
            detail="user_id and organization_id must match the authenticated session",
        )
    return await asyncio.to_thread(
        brain_execute,
        str(body.command).strip(),
        int(user.id),
        int(user.organization_id),
    )
