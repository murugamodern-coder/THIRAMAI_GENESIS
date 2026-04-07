"""
Long-term memory (Chroma) is populated via ``ltm_hooks``; this router exposes **HITL feedback**
to tune ``ai_rule_weights`` (policy strictness multipliers).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_roles
from services import hitl_rule_weights
from services.experience_buffer import clear_critical_mistake_record, record_critical_mistake

router = APIRouter(prefix="/ai", tags=["AI Memory & HITL"])


class HitlFeedbackBody(BaseModel):
    """``rule_key`` is usually a registered ``tool_id`` (e.g. ``inventory.sell_stock``)."""

    rule_key: str = Field(..., min_length=1, max_length=128)
    sentiment: int = Field(..., ge=-1, le=1, description="-1 tighten policy, 0 note, +1 loosen")
    comment: str = Field("", max_length=4000)


@router.post("/hitl/feedback")
async def submit_hitl_feedback(
    body: HitlFeedbackBody,
    _user: CurrentUser = Depends(require_roles("owner", "manager")),
) -> JSONResponse:
    out = hitl_rule_weights.record_feedback(
        organization_id=_user.organization_id,
        user_id=_user.id,
        rule_key=body.rule_key.strip(),
        sentiment=int(body.sentiment),
        comment=body.comment.strip(),
    )
    status = 200 if out.get("ok") else 400
    return JSONResponse(status_code=status, content=out)


@router.get("/hitl/rule-weight")
async def get_rule_weight(
    rule_key: str = Query(..., min_length=1, max_length=128),
    _user: CurrentUser = Depends(require_roles("owner", "manager")),
) -> JSONResponse:
    w = hitl_rule_weights.strictness_multiplier(_user.organization_id, rule_key)
    return JSONResponse(content={"rule_key": rule_key, "weight": w})


class CriticalMistakeBody(BaseModel):
    """Tag automation as a human override so policy will not repeat it for this org + tool."""

    tool_id: str = Field(..., min_length=1, max_length=256)
    summary: str = Field("", max_length=2000)
    context_key: str | None = Field(None, max_length=256)


@router.post("/experience/critical-mistake")
async def post_critical_mistake(
    body: CriticalMistakeBody,
    _user: CurrentUser = Depends(require_roles("owner", "manager")),
) -> JSONResponse:
    out = record_critical_mistake(
        organization_id=_user.organization_id,
        user_id=_user.id,
        tool_id=body.tool_id.strip(),
        summary=body.summary.strip(),
        context_key=(body.context_key or "").strip() or None,
    )
    return JSONResponse(content=out)


@router.post("/experience/critical-mistake/clear")
async def post_clear_critical_mistake(
    body: CriticalMistakeBody,
    _user: CurrentUser = Depends(require_roles("owner", "manager")),
) -> JSONResponse:
    out = clear_critical_mistake_record(
        organization_id=_user.organization_id,
        user_id=_user.id,
        tool_id=body.tool_id.strip(),
        context_key=(body.context_key or "").strip() or None,
    )
    return JSONResponse(content=out)
