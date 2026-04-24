"""Legacy ``/actions/*`` routes — forward execution to ``brain_execute``."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.action_execution_engine import (
    cancel_action_execution_run,
    confirm_action_execution_run,
    get_action_execution_run,
)
from services.async_task_queue import enqueue_task
from services.brain_execute import brain_execute
from services.brain_execute_adapter import brain_to_action_run_payload
from services.brain_execute_deprecation import warn_deprecated_execution_forwarded

router = APIRouter(tags=["Action Execution"])


class PlanBody(BaseModel):
    command: str = Field(..., min_length=2, max_length=8000)
    async_execution: bool = Field(default=False, description="Queue background worker when RQ is enabled")


class ConfirmBody(BaseModel):
    approve_batch_medium: bool = False
    explicit_step_ids: list[int] = Field(default_factory=list)


@router.post("/actions/plan")
async def post_action_plan(
    body: PlanBody,
    user: CurrentUser = Depends(require_permission("build_apps", "run_research", "manage_business", "view_personal")),
) -> dict[str, Any]:
    warn_deprecated_execution_forwarded("/actions/plan")
    if body.async_execution:
        queued = enqueue_task(
            "brain_execute_async",
            {
                "command": str(body.command),
                "user_id": int(user.id),
                "organization_id": int(user.organization_id),
            },
            job_timeout=3600,
        )
        if not queued.get("queued"):
            asyncio.create_task(
                asyncio.to_thread(
                    brain_execute,
                    str(body.command),
                    int(user.id),
                    int(user.organization_id),
                )
            )
        return {
            "ok": True,
            "queued": bool(queued.get("queued")),
            "mode": queued.get("mode", "inline"),
            "deprecated_forwarded_to_brain": True,
        }
    brain = await asyncio.to_thread(
        brain_execute,
        str(body.command),
        int(user.id),
        int(user.organization_id),
    )
    row = brain_to_action_run_payload(brain, user_id=int(user.id))
    if not row.get("run_id"):
        raise HTTPException(status_code=503, detail="brain_execute did not produce a persisted run")
    return row


@router.get("/actions/runs/{run_id}")
async def get_action_run(
    run_id: int,
    user: CurrentUser = Depends(require_permission("build_apps", "run_research", "manage_business", "view_personal")),
) -> dict[str, Any]:
    row = get_action_execution_run(run_id=int(run_id), user_id=int(user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return row


@router.post("/actions/runs/{run_id}/confirm")
async def post_action_confirm(
    run_id: int,
    body: ConfirmBody,
    user: CurrentUser = Depends(require_permission("build_apps", "run_research", "manage_business", "view_personal")),
) -> dict[str, Any]:
    warn_deprecated_execution_forwarded("/actions/runs/{id}/confirm")
    row = confirm_action_execution_run(
        run_id=int(run_id),
        user_id=int(user.id),
        approve_batch_medium=bool(body.approve_batch_medium),
        explicit_step_ids=list(body.explicit_step_ids or []),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return row


@router.post("/actions/runs/{run_id}/cancel")
async def post_action_cancel(
    run_id: int,
    user: CurrentUser = Depends(require_permission("build_apps", "run_research", "manage_business", "view_personal")),
) -> dict[str, Any]:
    warn_deprecated_execution_forwarded("/actions/runs/{id}/cancel")
    row = cancel_action_execution_run(run_id=int(run_id), user_id=int(user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"ok": True, "run": row}


@router.post("/actions/runs/{run_id}/execute")
async def post_action_execute(
    run_id: int,
    user: CurrentUser = Depends(require_permission("build_apps", "run_research", "manage_business", "view_personal")),
    async_execution: bool = False,
) -> dict[str, Any]:
    warn_deprecated_execution_forwarded("/actions/runs/{id}/execute")
    run = get_action_execution_run(run_id=int(run_id), user_id=int(user.id))
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    cmd = str(run.get("source_command") or "").strip()
    if not cmd:
        raise HTTPException(status_code=400, detail="Run has no source_command to forward to brain")
    if async_execution:
        queued = enqueue_task(
            "brain_execute_async",
            {
                "command": cmd,
                "user_id": int(user.id),
                "organization_id": int(user.organization_id),
            },
            job_timeout=3600,
        )
        if not queued.get("queued"):
            asyncio.create_task(
                asyncio.to_thread(
                    brain_execute,
                    cmd,
                    int(user.id),
                    int(user.organization_id),
                )
            )
        return {
            "ok": True,
            "requested_run_id": int(run_id),
            "queued": bool(queued.get("queued")),
            "mode": queued.get("mode", "inline"),
            "deprecated_forwarded_to_brain": True,
        }
    brain = await asyncio.to_thread(
        brain_execute,
        cmd,
        int(user.id),
        int(user.organization_id),
    )
    return {
        **brain,
        "deprecated_forwarded_to_brain": True,
        "requested_run_id": int(run_id),
    }
