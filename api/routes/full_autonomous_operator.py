"""Full autonomous operator mode: loop, deal intel, autonomy level, reliability, self-correction."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.full_autonomous_operator_mode import (
    add_execution_checkpoint,
    compute_dynamic_autonomy_mode,
    environment_awareness_scan,
    evolve_deal_intelligence,
    execution_reliability_by_domain,
    get_operator_snapshot,
    preflight_negotiation_with_intelligence,
    run_continuous_execution_loop,
    run_operator_mega_tick,
    run_strategy_evolution_loop,
    self_correct_on_mismatch,
)

router = APIRouter(tags=["Full autonomous operator"])


@router.post("/operator/execution-loop")
async def post_operator_execution_loop(
    max_items: int = Query(30, ge=1, le=100),
    stale_hours: int = Query(48, ge=4, le=168),
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return run_continuous_execution_loop(
        int(user.id),
        int(user.organization_id),
        max_items=int(max_items),
        stale_hours=int(stale_hours),
    )


class CheckpointBody(BaseModel):
    label: str = "checkpoint"
    detail: dict[str, Any] = Field(default_factory=dict)


@router.post("/operator/executions/{public_id}/checkpoint")
async def post_operator_checkpoint(
    public_id: str,
    body: CheckpointBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return add_execution_checkpoint(str(public_id), int(user.id), body.label, body.detail)


@router.post("/operator/deal-intelligence/evolve")
async def post_deal_intelligence_evolve(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return evolve_deal_intelligence(int(user.id))


@router.get("/operator/autonomy-mode")
async def get_operator_autonomy_mode(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return compute_dynamic_autonomy_mode(int(user.id), int(user.organization_id))


@router.get("/operator/reliability")
async def get_operator_reliability(
    limit: int = Query(200, ge=20, le=500),
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return execution_reliability_by_domain(int(user.id), limit=int(limit))


class SelfCorrectBody(BaseModel):
    execution_public_id: str = Field(..., min_length=4, max_length=64)


@router.post("/operator/self-correct")
async def post_operator_self_correct(
    body: SelfCorrectBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return self_correct_on_mismatch(int(user.id), int(user.organization_id), str(body.execution_public_id).strip())


@router.get("/operator/snapshot")
async def get_operator_full_snapshot(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return get_operator_snapshot(int(user.id))


@router.get("/operator/negotiation-deals/{public_id}/preflight")
async def get_negotiation_preflight(
    public_id: str,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return preflight_negotiation_with_intelligence(str(public_id), int(user.id))


@router.post("/operator/strategy-evolution")
async def post_strategy_evolution(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return run_strategy_evolution_loop(int(user.id), int(user.organization_id))


@router.post("/operator/environment-scan")
async def post_environment_scan(
    max_items: int = Query(24, ge=1, le=50),
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return environment_awareness_scan(int(user.id), int(user.organization_id), max_items=int(max_items))


@router.post("/operator/mega-tick")
async def post_operator_mega_tick(
    max_items: int = Query(30, ge=1, le=100),
    stale_hours: int = Query(48, ge=4, le=168),
    with_strategy: bool = Query(False, description="Run full strategy generate/test/promote (heavier)"),
    with_deal_evolve: bool = Query(
        False, description="Run deal intelligence + playbook update (heavier; often scheduled separately)"
    ),
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return run_operator_mega_tick(
        int(user.id),
        int(user.organization_id),
        max_items=int(max_items),
        stale_hours=int(stale_hours),
        with_strategy=bool(with_strategy),
        with_deal_evolve=bool(with_deal_evolve),
    )
