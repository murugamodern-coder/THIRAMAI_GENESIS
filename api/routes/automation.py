"""Automation rules and activity APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.automation_rule_engine import (
    delete_rule,
    evaluate_rules,
    list_automation_logs,
    list_rules,
    upsert_rule,
)
from services.async_task_queue import enqueue_task

router = APIRouter(tags=["Automation"])


class RuleUpsertBody(BaseModel):
    id: int | None = None
    name: str = Field(..., min_length=1, max_length=200)
    trigger_type: str = Field(..., min_length=1, max_length=64)
    condition_json: dict[str, Any] = Field(default_factory=dict)
    action_type: str = Field(..., min_length=1, max_length=64)
    action_config_json: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class EvaluateEventBody(BaseModel):
    trigger_type: str = Field(..., min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)


@router.get("/automation/rules")
async def get_automation_rules(
    user: CurrentUser = Depends(require_permission("manage_business", "build_apps", "run_research")),
) -> dict[str, Any]:
    return {"ok": True, "items": list_rules(int(user.id))}


@router.post("/automation/rules")
async def post_automation_rule(
    body: RuleUpsertBody,
    user: CurrentUser = Depends(require_permission("manage_business", "build_apps", "run_research")),
) -> dict[str, Any]:
    out = upsert_rule(
        user_id=int(user.id),
        rule_id=body.id,
        name=body.name,
        trigger_type=body.trigger_type,
        condition_json=body.condition_json,
        action_type=body.action_type,
        action_config_json=body.action_config_json,
        enabled=body.enabled,
    )
    if out is None:
        raise HTTPException(status_code=500, detail="Unable to save rule")
    return {"ok": True, **out}


@router.delete("/automation/rules/{rule_id}")
async def remove_automation_rule(
    rule_id: int,
    user: CurrentUser = Depends(require_permission("manage_business", "build_apps", "run_research")),
) -> dict[str, Any]:
    ok = delete_rule(user_id=int(user.id), rule_id=int(rule_id))
    if not ok:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"ok": True}


@router.get("/automation/logs")
async def get_automation_logs(
    limit: int = Query(80, ge=1, le=200),
    user: CurrentUser = Depends(require_permission("manage_business", "build_apps", "run_research")),
) -> dict[str, Any]:
    return {"ok": True, "items": list_automation_logs(user_id=int(user.id), limit=limit)}


@router.post("/automation/evaluate")
async def post_evaluate_automation(
    body: EvaluateEventBody,
    user: CurrentUser = Depends(require_permission("manage_business", "build_apps", "run_research")),
) -> dict[str, Any]:
    event = {
        "user_id": int(user.id),
        "organization_id": int(user.organization_id),
        "role_name": str(user.role_name or ""),
        "trigger_type": body.trigger_type,
        "payload": body.payload or {},
    }
    queued = enqueue_task("automation_evaluate", event)
    if queued.get("queued"):
        return {"ok": True, "queued": True, "job_id": queued.get("job_id")}
    return evaluate_rules(event)
