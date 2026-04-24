"""Invention loop: gaps, ideas, hypotheses, validation, compare, promote."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.invention_loop_engine import (
    collect_innovation_gaps,
    compare_invention_runs,
    create_hypotheses_for_idea,
    ideas_from_gaps,
    promote_best_idea,
    run_invention_loop,
    validate_idea,
)

router = APIRouter(tags=["Invention loop"])


class ValidateBody(BaseModel):
    idea: dict[str, Any] = Field(default_factory=dict)
    method: str = "simulation"


@router.get("/invention-loop/gaps")
async def get_invention_gaps(
    user: CurrentUser = Depends(require_permission("run_research", "manage_business", "trade_stock")),
) -> dict[str, Any]:
    return collect_innovation_gaps(int(user.id), int(user.organization_id))


@router.get("/invention-loop/ideas")
async def get_invention_ideas(
    max_ideas: int = Query(4, ge=1, le=8),
    user: CurrentUser = Depends(require_permission("run_research", "manage_business", "trade_stock")),
) -> dict[str, Any]:
    return ideas_from_gaps(int(user.id), int(user.organization_id), max_ideas=int(max_ideas))


@router.post("/invention-loop/hypotheses")
async def post_invention_hypotheses(
    body: ValidateBody,
    user: CurrentUser = Depends(require_permission("run_research", "manage_business", "trade_stock")),
) -> dict[str, Any]:
    return create_hypotheses_for_idea(int(user.id), body.idea or {})


@router.post("/invention-loop/validate")
async def post_invention_validate(
    body: ValidateBody,
    user: CurrentUser = Depends(require_permission("run_research", "manage_business", "trade_stock")),
) -> dict[str, Any]:
    return validate_idea(
        int(user.id),
        int(user.organization_id),
        body.idea or {},
        method=str(body.method or "simulation"),
    )


class CompareBody(BaseModel):
    runs: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/invention-loop/compare")
async def post_invention_compare(
    body: CompareBody,
    user: CurrentUser = Depends(require_permission("run_research", "manage_business", "trade_stock")),
) -> dict[str, Any]:
    _ = user
    return compare_invention_runs(list(body.runs or []))


class PromoteBody(BaseModel):
    best: dict[str, Any] | None = None


@router.post("/invention-loop/promote")
async def post_invention_promote(
    body: PromoteBody,
    user: CurrentUser = Depends(require_permission("run_research", "manage_business", "trade_stock")),
) -> dict[str, Any]:
    return promote_best_idea(int(user.id), int(user.organization_id), body.best)


@router.post("/invention-loop/cycle")
async def post_invention_cycle(
    validation: str = Query("simulation", description="simulation | research | both"),
    max_ideas: int = Query(4, ge=1, le=8),
    user: CurrentUser = Depends(require_permission("run_research", "manage_business", "trade_stock")),
) -> dict[str, Any]:
    return run_invention_loop(
        int(user.id),
        int(user.organization_id),
        validation=str(validation or "simulation"),
        max_ideas=int(max_ideas),
    )
