"""Research Loop Engine APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.research_loop_engine import (
    compare_experiment_results,
    generate_hypotheses,
    promote_strategy_update,
    run_experiment,
)

router = APIRouter(tags=["Research Loop"])


class ExperimentRunBody(BaseModel):
    hypothesis_id: str = Field(..., min_length=1, max_length=128)
    variant_config: dict[str, Any] = Field(default_factory=dict)


@router.post("/research-loop/hypotheses")
async def post_research_hypotheses(
    domain: str = "general",
    user: CurrentUser = Depends(require_permission("run_research", "manage_business")),
) -> dict[str, Any]:
    return generate_hypotheses(int(user.id), str(domain or "general"))


@router.post("/research-loop/experiments/run")
async def post_research_experiment_run(
    body: ExperimentRunBody,
    user: CurrentUser = Depends(require_permission("run_research", "manage_business")),
) -> dict[str, Any]:
    return run_experiment(
        int(user.id),
        int(user.organization_id),
        str(body.hypothesis_id),
        body.variant_config or {},
    )


@router.get("/research-loop/experiments/{experiment_group_id}/compare")
async def get_research_experiment_compare(
    experiment_group_id: str,
    user: CurrentUser = Depends(require_permission("run_research", "manage_business")),
) -> dict[str, Any]:
    return compare_experiment_results(int(user.id), str(experiment_group_id))


@router.post("/research-loop/experiments/{experiment_group_id}/promote")
async def post_research_experiment_promote(
    experiment_group_id: str,
    user: CurrentUser = Depends(require_permission("run_research", "manage_business")),
) -> dict[str, Any]:
    return promote_strategy_update(int(user.id), str(experiment_group_id))
