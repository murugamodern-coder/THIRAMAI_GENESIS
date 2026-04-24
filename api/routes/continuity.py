"""Autonomous Continuity Engine — persistent goals, background ticks, environment, settings."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.autonomous_continuity_engine import (
    build_environment_context,
    create_goal,
    get_or_create_settings,
    list_goals,
    resume_continuity_goal,
    run_continuity_tick,
    upsert_settings,
    update_goal,
)

router = APIRouter(tags=["Autonomous Continuity"])


def _parse_deadline(raw: str | None) -> datetime | None:
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


class ContinuitySettingsPatch(BaseModel):
    autonomy_level: str | None = None
    enabled: bool | None = None
    time_budget_minutes_per_day: int | None = Field(default=None, ge=1, le=1440)
    capital_budget: float | None = Field(default=None, ge=0)
    effort_budget: int | None = Field(default=None, ge=1, le=500)
    allow_auto_batch_medium: bool | None = None


class ContinuityCreateGoalBody(BaseModel):
    objective: str = Field(..., min_length=1, max_length=20000)
    priority: int = Field(default=3, ge=1, le=5)
    deadline: str | None = None


class ContinuityPatchGoalBody(BaseModel):
    objective: str | None = Field(default=None, max_length=20000)
    priority: int | None = Field(default=None, ge=1, le=5)
    deadline: str | None = None
    clear_deadline: bool = False
    status: str | None = Field(
        default=None,
        max_length=32,
    )
    progress_pct: float | None = Field(default=None, ge=0, le=100)
    total_steps_est: int | None = Field(default=None, ge=0)
    remaining_actions: dict[str, Any] | None = None
    completed_steps: dict[str, Any] | None = None
    meta_patch: dict[str, Any] | None = None


class ResumeBody(BaseModel):
    resume_command: str | None = Field(default=None, max_length=8000)


@router.get("/autonomy/continuity/settings")
async def get_continuity_settings(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    s = get_or_create_settings(user_id=int(user.id), organization_id=int(user.organization_id))
    return {"ok": True, "settings": s}


@router.patch("/autonomy/continuity/settings")
async def patch_continuity_settings(
    body: ContinuitySettingsPatch,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    p = body.model_dump(exclude_unset=True)
    if not p:
        s = get_or_create_settings(user_id=int(user.id), organization_id=int(user.organization_id))
        return {"ok": True, "settings": s}
    u = upsert_settings(user_id=int(user.id), organization_id=int(user.organization_id), **p)
    if u is None:
        raise HTTPException(503, "Continuity settings unavailable (database)")
    return {"ok": True, "settings": u}


@router.get("/autonomy/continuity/environment")
async def get_continuity_environment(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    env = build_environment_context(user_id=int(user.id), organization_id=int(user.organization_id))
    return {"ok": True, "environment": env}


@router.get("/autonomy/continuity/goals")
async def get_continuity_goals(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
    status: list[str] | None = Query(
        default=None,
        description="Repeat param for each status, e.g. status=active&status=interrupted",
    ),
) -> dict[str, Any]:
    st = list(status) if status else None
    goals = list_goals(
        user_id=int(user.id),
        organization_id=int(user.organization_id),
        statuses=st,
    )
    return {"ok": True, "goals": goals, "count": len(goals)}


@router.post("/autonomy/continuity/goals")
async def post_continuity_goal(
    body: ContinuityCreateGoalBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    dl: datetime | None
    try:
        dl = _parse_deadline(body.deadline)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, f"Invalid deadline: {e}") from e
    g = create_goal(
        user_id=int(user.id),
        organization_id=int(user.organization_id),
        objective=body.objective,
        priority=int(body.priority),
        deadline=dl,
    )
    if g is None:
        raise HTTPException(400, "Could not create goal")
    return {"ok": True, "goal": g}


@router.patch("/autonomy/continuity/goals/{goal_id}")
async def patch_continuity_goal(
    goal_id: int,
    body: ContinuityPatchGoalBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    d = body.model_dump(exclude_unset=True)
    meta_patch = d.pop("meta_patch", None)
    d.pop("clear_deadline", None)
    rem = d.pop("remaining_actions", None)
    comp = d.pop("completed_steps", None)
    raw_dead = d.pop("deadline", None) if "deadline" in body.model_fields_set else None

    dl: datetime | None
    if raw_dead is not None and not body.clear_deadline:
        try:
            dl = _parse_deadline(str(raw_dead))
        except (ValueError, TypeError) as e:
            raise HTTPException(400, f"Invalid deadline: {e}") from e
    else:
        dl = None

    kwargs: dict[str, Any] = {}
    for k, v in d.items():
        if v is not None:
            kwargs[k] = v
    if rem is not None:
        kwargs["remaining_actions_json"] = rem
    if comp is not None:
        kwargs["completed_steps_json"] = comp

    g = update_goal(
        user_id=int(user.id),
        goal_id=int(goal_id),
        **kwargs,
        clear_deadline=bool(body.clear_deadline),
        deadline=dl,
        extra_meta=meta_patch,
    )
    if g is None:
        raise HTTPException(404, "Goal not found")
    return {"ok": True, "goal": g}


@router.post("/autonomy/continuity/goals/{goal_id}/resume")
async def post_continuity_goal_resume(
    goal_id: int,
    body: ResumeBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    g = resume_continuity_goal(
        user_id=int(user.id),
        goal_id=int(goal_id),
        resume_command=body.resume_command,
    )
    if g is None:
        raise HTTPException(404, "Goal not found")
    return {"ok": True, "goal": g}


@router.post("/autonomy/continuity/tick")
async def post_continuity_tick(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
    role: Annotated[str, Query(description="Routed into action engine context; default owner")] = "owner",
) -> dict[str, Any]:
    r = str(role) if str(role) in ("owner", "admin", "operator", "user") else "owner"
    return run_continuity_tick(
        int(user.id),
        int(user.organization_id),
        role_name=r,
    )
