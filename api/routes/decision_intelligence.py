"""Decision intelligence: A/B/C options, recommendation, outcome → learning."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.decision_intelligence_engine import (
    build_decision_analysis,
    create_and_save_decision,
    get_decision_session,
    list_decision_sessions,
    record_decision_outcome,
    select_decision_option,
)

router = APIRouter(tags=["Decision Intelligence"])


class DecisionAnalyzeBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    decision_brief: str = Field(..., min_length=4, max_length=20000, description="Full decision context, constraints, stakes")
    context: dict[str, Any] = Field(default_factory=dict, description="Optional: expected_profit_baseline, stake, etc.")


class DecisionCreateBody(DecisionAnalyzeBody):
    """Same as analyze but persists a session."""


class SelectOptionBody(BaseModel):
    option: Literal["A", "B", "C"] = Field(..., description="Aggressive / Balanced / Safe")


class OutcomeBody(BaseModel):
    success: bool
    notes: str = Field(default="", max_length=4000)
    value_realized: float | None = None
    selected_option: str | None = Field(
        default=None,
        description="If you skipped POST .../select, you may set A|B|C here once.",
    )


@router.post("/decision/analyze")
async def post_decision_analyze(
    body: DecisionAnalyzeBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research", "view_personal")),
) -> dict[str, Any]:
    return build_decision_analysis(
        user_id=int(user.id),
        title=body.title,
        decision_brief=body.decision_brief,
        context=body.context or {},
    )


@router.post("/decision/sessions")
async def post_decision_session(
    body: DecisionCreateBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research", "view_personal")),
) -> dict[str, Any]:
    r = create_and_save_decision(
        user_id=int(user.id),
        organization_id=int(user.organization_id),
        title=body.title,
        decision_brief=body.decision_brief,
        context=body.context or {},
    )
    if r is None:
        raise HTTPException(503, "Unable to create session")
    if r.get("error") == "database_unavailable":
        return r
    return r


@router.get("/decision/sessions")
async def get_decision_sessions(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research", "view_personal")),
    limit: int = Query(30, ge=1, le=100),
) -> dict[str, Any]:
    return {"ok": True, "items": list_decision_sessions(user_id=int(user.id), limit=limit)}


@router.get("/decision/sessions/{session_id}")
async def get_decision_session_by_id(
    session_id: int,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research", "view_personal")),
) -> dict[str, Any]:
    r = get_decision_session(session_id=int(session_id), user_id=int(user.id))
    if r is None:
        raise HTTPException(404, "Session not found")
    return {"ok": True, "session": r}


@router.post("/decision/sessions/{session_id}/select")
async def post_decision_select(
    session_id: int,
    body: SelectOptionBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research", "view_personal")),
) -> dict[str, Any]:
    r = select_decision_option(session_id=int(session_id), user_id=int(user.id), option=body.option)
    if r is None:
        raise HTTPException(404, "Session not found or invalid option")
    return {"ok": True, "session": r}


@router.post("/decision/sessions/{session_id}/outcome")
async def post_decision_outcome(
    session_id: int,
    body: OutcomeBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research", "view_personal")),
) -> dict[str, Any]:
    r = record_decision_outcome(
        session_id=int(session_id),
        user_id=int(user.id),
        organization_id=int(user.organization_id),
        success=body.success,
        notes=body.notes,
        value_realized=body.value_realized,
        selected_option=body.selected_option,
    )
    if r is None:
        raise HTTPException(404, "Session not found")
    return r
