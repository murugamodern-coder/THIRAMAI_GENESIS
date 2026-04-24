"""Simulation APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.autonomy_sandbox_experiment import run_autonomy_sandbox_experiment
from services.evolution_gate_engine import record_promotion_feedback, run_controlled_evolution_gate
from services.simulation_engine import choose_best_simulated_path, simulate_action_paths

router = APIRouter(tags=["Simulation"])


class SimulationBody(BaseModel):
    action_context: dict[str, Any] = Field(default_factory=dict)


class AutonomySandboxBody(BaseModel):
    sandbox_context: dict[str, Any] = Field(default_factory=dict)


class EvolutionGateBody(BaseModel):
    sandbox_context: dict[str, Any] = Field(default_factory=dict)
    sandbox_output: dict[str, Any] = Field(default_factory=dict)


class EvolutionGateFeedbackBody(BaseModel):
    promotion_id: str
    success: bool = True
    roi: float = 0.0
    note: str = ""


@router.post("/simulation/run")
async def post_simulation_run(
    body: SimulationBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return simulate_action_paths(int(user.id), body.action_context or {})


@router.post("/simulation/choose")
async def post_simulation_choose(
    body: SimulationBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return choose_best_simulated_path(int(user.id), body.action_context or {})


@router.post("/simulation/autonomy-sandbox")
async def post_autonomy_sandbox(
    body: AutonomySandboxBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    _ = user
    return run_autonomy_sandbox_experiment(sandbox_context=body.sandbox_context or {})


@router.post("/simulation/evolution-gate")
async def post_evolution_gate(
    body: EvolutionGateBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    sandbox_output = body.sandbox_output or {}
    if not sandbox_output:
        sandbox_output = run_autonomy_sandbox_experiment(sandbox_context=body.sandbox_context or {})
    return run_controlled_evolution_gate(
        user_id=int(user.id),
        organization_id=int(user.organization_id),
        sandbox_output=sandbox_output,
    )


@router.post("/simulation/evolution-gate/feedback")
async def post_evolution_gate_feedback(
    body: EvolutionGateFeedbackBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return record_promotion_feedback(
        user_id=int(user.id),
        organization_id=int(user.organization_id),
        promotion_id=str(body.promotion_id),
        success=bool(body.success),
        roi=float(body.roi),
        note=str(body.note or ""),
    )
