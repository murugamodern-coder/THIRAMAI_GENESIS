"""Governance and control center APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.governance_engine import (
    list_execution_logs,
    list_guardrails,
    set_kill_switch,
    upsert_guardrail,
)

router = APIRouter(tags=["Governance"])


class GuardrailBody(BaseModel):
    id: int | None = None
    rule_name: str = Field(..., min_length=1, max_length=120)
    domain: str = Field(..., min_length=1, max_length=32)
    condition_json: dict[str, Any] = Field(default_factory=dict)
    action_limit_json: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class KillSwitchBody(BaseModel):
    enabled: bool = True
    reason: str = ""


@router.get("/governance/guardrails")
async def get_governance_guardrails(
    user: CurrentUser = Depends(require_permission("manage_business", "build_apps", "trade_stock")),
) -> dict[str, Any]:
    return {"ok": True, "items": list_guardrails(int(user.id))}


@router.post("/governance/guardrails")
async def post_governance_guardrail(
    body: GuardrailBody,
    user: CurrentUser = Depends(require_permission("manage_business", "build_apps", "trade_stock")),
) -> dict[str, Any]:
    out = upsert_guardrail(
        user_id=int(user.id),
        guardrail_id=body.id,
        rule_name=body.rule_name,
        domain=body.domain,
        condition_json=body.condition_json or {},
        action_limit_json=body.action_limit_json or {},
        enabled=bool(body.enabled),
    )
    if out is None:
        raise HTTPException(status_code=500, detail="Unable to save guardrail")
    return {"ok": True, **out}


@router.post("/governance/kill-switch")
async def post_governance_kill_switch(
    body: KillSwitchBody,
    user: CurrentUser = Depends(require_permission("manage_business", "build_apps", "trade_stock")),
) -> dict[str, Any]:
    out = set_kill_switch(user_id=int(user.id), enabled=bool(body.enabled), reason=body.reason)
    if out is None:
        raise HTTPException(status_code=500, detail="Unable to update kill switch")
    return {"ok": True, **out}


@router.get("/governance/logs")
async def get_governance_logs(
    limit: int = Query(150, ge=1, le=500),
    user: CurrentUser = Depends(require_permission("manage_business", "build_apps", "trade_stock")),
) -> dict[str, Any]:
    out = list_execution_logs(int(user.id), limit=limit)
    return {"ok": True, **out}
