"""Real-world autonomous execution: tracking, negotiation loop, confidence, truth, feedback."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.real_world_autonomous_layer import (
    append_negotiation_message,
    capture_real_world_feedback,
    create_negotiation_deal,
    create_real_world_execution,
    evaluate_autonomy_confidence,
    get_negotiation_deal,
    list_real_world_executions,
    negotiation_counter_suggestion,
    record_outcome_truth,
    run_negotiation_turn,
    set_deal_status,
    set_execution_state,
    confirm_real_world_closure,
    verify_execution_outcome,
    reconcile_execution_state,
)

router = APIRouter(tags=["Real-world autonomy"])


# --- Executions ---

class CreateExecutionBody(BaseModel):
    action_type: str = "general"
    label: str = ""
    expected_outcome: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)


@router.post("/real-world-execution")
async def post_create_execution(
    body: CreateExecutionBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return create_real_world_execution(
        int(user.id),
        int(user.organization_id),
        action_type=body.action_type,
        label=body.label,
        expected_outcome=body.expected_outcome,
        meta=body.meta,
    )


class StateBody(BaseModel):
    state: str
    actual_outcome: dict[str, Any] | None = None
    api_succeeded: bool | None = None


@router.patch("/real-world-execution/{public_id}/state")
async def patch_execution_state(
    public_id: str,
    body: StateBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return set_execution_state(
        str(public_id),
        int(user.id),
        body.state,
        actual_outcome=body.actual_outcome,
        api_succeeded=body.api_succeeded,
    )


class VerifyBody(BaseModel):
    actual_outcome: dict[str, Any] = Field(default_factory=dict)
    api_succeeded: bool = True
    note: str = ""
    require_external_closure: bool = False


@router.post("/real-world-execution/{public_id}/verify")
async def post_verify_execution(
    public_id: str,
    body: VerifyBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return verify_execution_outcome(
        str(public_id),
        int(user.id),
        int(user.organization_id),
        actual_outcome=body.actual_outcome,
        api_succeeded=body.api_succeeded,
        note=body.note,
        require_external_closure=body.require_external_closure,
    )


class ClosureBody(BaseModel):
    external_confirmed: bool = True
    reconciled: bool = True
    note: str = ""


@router.post("/real-world-execution/{public_id}/closure")
async def post_execution_closure(
    public_id: str,
    body: ClosureBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return confirm_real_world_closure(
        str(public_id),
        int(user.id),
        int(user.organization_id),
        external_confirmed=body.external_confirmed,
        reconciled=body.reconciled,
        note=body.note,
    )


@router.post("/real-world-execution/{public_id}/reconcile")
async def post_execution_reconcile(
    public_id: str,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return reconcile_execution_state(str(public_id), int(user.id))


@router.get("/real-world-execution")
async def get_executions(
    state: str | None = None,
    limit: int = Query(40, ge=1, le=200),
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return list_real_world_executions(int(user.id), state=state, limit=limit)


# --- Negotiation ---

class NewDealBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    context: dict[str, Any] = Field(default_factory=dict)


@router.post("/negotiation-deals")
async def post_new_deal(
    body: NewDealBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return create_negotiation_deal(int(user.id), int(user.organization_id), body.title, body.context)


@router.get("/negotiation-deals/{public_id}")
async def get_deal(
    public_id: str,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return get_negotiation_deal(str(public_id), int(user.id))


class MessageBody(BaseModel):
    role: str = "outbound"
    body: str = ""


@router.post("/negotiation-deals/{public_id}/message")
async def post_deal_message(
    public_id: str,
    body: MessageBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return append_negotiation_message(str(public_id), int(user.id), body.role, body.body)


@router.post("/negotiation-deals/{public_id}/turn")
async def post_deal_turn(
    public_id: str,
    body: MessageBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return run_negotiation_turn(
        str(public_id),
        int(user.id),
        body.body,
    )


@router.get("/negotiation-deals/{public_id}/counter")
async def get_deal_counter(
    public_id: str,
    role: Literal["buyer", "seller"] = "buyer",
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return negotiation_counter_suggestion(str(public_id), int(user.id), role=role)


class DealStatusBody(BaseModel):
    status: str


@router.post("/negotiation-deals/{public_id}/status")
async def post_deal_status(
    public_id: str,
    body: DealStatusBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return set_deal_status(str(public_id), int(user.id), body.status)


# --- Confidence / truth / feedback ---

class ConfidenceContextBody(BaseModel):
    context: dict[str, Any] = Field(default_factory=dict)


@router.get("/autonomy/confidence")
async def get_autonomy_confidence(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return evaluate_autonomy_confidence(int(user.id))


@router.post("/autonomy/confidence")
async def post_autonomy_confidence(
    body: ConfidenceContextBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return evaluate_autonomy_confidence(int(user.id), context=body.context)


class TruthBody(BaseModel):
    execution_public_id: str
    expected: dict[str, Any] = Field(default_factory=dict)
    actual: dict[str, Any] = Field(default_factory=dict)
    adjust_profiles: bool = True


@router.post("/outcome-truth/record")
async def post_outcome_truth(
    body: TruthBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return record_outcome_truth(
        int(user.id),
        int(user.organization_id),
        body.execution_public_id,
        body.expected,
        body.actual,
        adjust_profiles=body.adjust_profiles,
    )


class FeedbackBody(BaseModel):
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)


@router.post("/real-world-feedback")
async def post_real_world_feedback(
    body: FeedbackBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return capture_real_world_feedback(
        int(user.id),
        int(user.organization_id),
        body.kind,
        body.payload,
    )
