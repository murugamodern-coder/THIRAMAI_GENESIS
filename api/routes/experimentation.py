"""Experimentation engine: strategy trials, history, success/failure patterns."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.experimentation_engine import (
    compare_success_failure_patterns,
    complete_experiment,
    create_experiment_for_strategy,
    list_experiment_history,
    run_strategy_trial,
    set_experiment_execution,
)

router = APIRouter(tags=["Experimentation"])


class CreateExperimentBody(BaseModel):
    strategy: dict[str, Any] = Field(default_factory=dict)
    hypothesis: str = ""
    experiment_group: str = "custom"


class CompleteBody(BaseModel):
    result: dict[str, Any] = Field(default_factory=dict)
    success: bool | None = None
    sync_strategy_profiles: bool = True


class ExecutionBody(BaseModel):
    execution: dict[str, Any] = Field(default_factory=dict)


class TrialBody(BaseModel):
    strategy: dict[str, Any] = Field(default_factory=dict)
    hypothesis: str = ""
    execution: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    success: bool | None = None
    experiment_group: str = "strategy_workspace"
    sync_strategy_profiles: bool = False


@router.post("/experiments/strategy/create")
async def post_create_strategy_experiment(
    body: CreateExperimentBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return create_experiment_for_strategy(
        int(user.id),
        int(user.organization_id),
        body.strategy,
        body.hypothesis,
        experiment_group=body.experiment_group,
    )


@router.post("/experiments/{experiment_id}/execution")
async def post_experiment_execution(
    experiment_id: int,
    body: ExecutionBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return set_experiment_execution(int(experiment_id), int(user.id), body.execution)


@router.post("/experiments/{experiment_id}/complete")
async def post_experiment_complete(
    experiment_id: int,
    body: CompleteBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return complete_experiment(
        int(experiment_id),
        int(user.id),
        int(user.organization_id),
        body.result,
        success=body.success,
        sync_strategy_profiles=body.sync_strategy_profiles,
    )


@router.post("/experiments/strategy/trial")
async def post_strategy_trial(
    body: TrialBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return run_strategy_trial(
        int(user.id),
        int(user.organization_id),
        body.strategy,
        body.hypothesis,
        body.execution,
        body.result,
        experiment_group=body.experiment_group,
        success=body.success,
        sync_strategy_profiles=body.sync_strategy_profiles,
    )


@router.get("/experiments/compare")
async def get_experiment_compare(
    experiment_group: str | None = None,
    limit: int = Query(200, ge=10, le=500),
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return compare_success_failure_patterns(int(user.id), experiment_group=experiment_group, limit=limit)


@router.get("/experiments/history")
async def get_experiment_history(
    experiment_group: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10_000),
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return list_experiment_history(int(user.id), experiment_group=experiment_group, limit=limit, offset=offset)
