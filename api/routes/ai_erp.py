"""
AI ERP bridge — runs the multi-agent business cycle (read-mostly + gated execution).
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_roles
from core.autonomous_loop import autonomous_mode_enabled
from services.ai_erp_bridge import ai_business_cycle

router = APIRouter(prefix="/ai/erp", tags=["AI ERP"])


class BusinessCycleBody(BaseModel):
    """Optional flags merged into the cycle context."""

    auto_mode: bool = Field(False, description="When true, allows allow-listed auto intents (see multi_agent_cycle)")
    extra_context: dict[str, Any] = Field(default_factory=dict)


@router.post("/business-cycle")
async def run_business_cycle(
    body: BusinessCycleBody = Body(default_factory=BusinessCycleBody),
    _user: CurrentUser = Depends(require_roles("owner", "manager", "admin")),
) -> JSONResponse:
    """
    One pass through revenue analysis, business decisions, prioritization, action planning, and workers.

    **Safety:** financial sells are not auto-executed from this path; ``auto_mode`` only enables
    narrowly allow-listed intents (e.g. add/read inventory). Autonomous scheduler uses the same engines.
    """
    ctx: dict[str, Any] = {
        **(body.extra_context or {}),
        "organization_id": int(_user.organization_id),
        "user_id": int(_user.id) if _user.id > 0 else None,
        "role_level": int(_user.role_level),
        "actor_role_name": (_user.role_name or "owner").lower(),
        "auto_mode": bool(body.auto_mode),
    }
    out = await asyncio.to_thread(ai_business_cycle, ctx)
    out["autonomous_scheduler_enabled"] = autonomous_mode_enabled()
    return JSONResponse(content=out)
