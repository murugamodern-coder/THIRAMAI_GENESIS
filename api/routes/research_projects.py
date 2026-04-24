"""Persistent research workspace and overnight run APIs."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.async_task_queue import enqueue_task
from services.research_projects_engine import (
    create_research_project,
    get_research_project,
    list_research_projects,
    run_research_project,
)

router = APIRouter(tags=["Research Projects"])


class ResearchProjectCreateBody(BaseModel):
    title: str = Field(..., min_length=3, max_length=300)
    domain: str = Field("general", min_length=2, max_length=64)


class ResearchProjectRunBody(BaseModel):
    cycles: int = Field(3, ge=1, le=12)


@router.get("/research/projects")
async def get_projects(
    limit: int = 80,
    user: CurrentUser = Depends(require_permission("run_research", "manage_business")),
) -> dict[str, Any]:
    return list_research_projects(int(user.id), limit=limit)


@router.post("/research/projects")
async def post_create_project(
    body: ResearchProjectCreateBody,
    user: CurrentUser = Depends(require_permission("run_research", "manage_business")),
) -> dict[str, Any]:
    out = create_research_project(
        user_id=int(user.id),
        organization_id=int(user.organization_id),
        title=str(body.title or ""),
        domain=str(body.domain or "general"),
    )
    if not out.get("ok"):
        raise HTTPException(status_code=503, detail=str(out.get("error") or "Unable to create project"))
    return out


@router.post("/research/projects/{project_id}/run")
async def post_run_project(
    project_id: int,
    body: ResearchProjectRunBody,
    user: CurrentUser = Depends(require_permission("run_research", "manage_business")),
) -> dict[str, Any]:
    project = get_research_project(int(user.id), int(project_id))
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    queued = enqueue_task(
        "research_project_run",
        {"project_id": int(project_id), "cycles": int(body.cycles)},
        job_timeout=8 * 3600,
    )
    if not queued.get("queued"):
        asyncio.create_task(asyncio.to_thread(run_research_project, int(project_id), int(body.cycles)))
    return {"ok": True, "project_id": int(project_id), "queued": bool(queued.get("queued")), "status": "running"}


@router.get("/research/projects/{project_id}")
async def get_project(
    project_id: int,
    user: CurrentUser = Depends(require_permission("run_research", "manage_business")),
) -> dict[str, Any]:
    row = get_research_project(int(user.id), int(project_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return row


@router.get("/research/projects/{project_id}/results")
async def get_project_results(
    project_id: int,
    user: CurrentUser = Depends(require_permission("run_research", "manage_business")),
) -> dict[str, Any]:
    row = get_research_project(int(user.id), int(project_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return {
        "ok": True,
        "project_id": int(project_id),
        "status": row.get("status"),
        "outputs": row.get("outputs") or {},
        "last_error": row.get("last_error"),
    }
