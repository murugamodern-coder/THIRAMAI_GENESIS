"""Domain domination: vertical focus, knowledge, pipeline, P&L, strategy loop."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.domain_dominion_engine import (
    ALLOWED_DOMAINS,
    get_action_templates,
    get_or_create_profile,
    list_domain_connectors,
    merge_knowledge,
    record_domain_revenue_event,
    domain_pnl_summary,
    run_domain_opportunity_pipeline,
    run_weekly_domain_strategy_review,
    set_active_domain,
)

router = APIRouter(tags=["Domain Domination"])


class DomainSetBody(BaseModel):
    active_domain: str = Field(..., min_length=2, max_length=64)
    enabled: bool | None = None


class KnowledgeMergeBody(BaseModel):
    section: Literal["tools", "suppliers", "workflows", "regulations", "other"] = "tools"
    items: list[dict[str, Any]] | list[str] = Field(default_factory=list)


class RevenueEventBody(BaseModel):
    event_type: Literal["income", "cost", "adjustment"] = "income"
    amount: float
    note: str = Field(default="", max_length=2000)
    domain: str = ""


@router.get("/domain/focus")
async def get_domain_focus(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    p = get_or_create_profile(user_id=int(user.id), organization_id=int(user.organization_id))
    return {"ok": True, "profile": p, "allowed_domains": sorted(ALLOWED_DOMAINS)}


@router.put("/domain/focus")
async def put_domain_focus(
    body: DomainSetBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    p = set_active_domain(
        user_id=int(user.id),
        organization_id=int(user.organization_id),
        domain=body.active_domain,
        enabled=body.enabled,
    )
    if p is None:
        return {"ok": False, "error": "database_unavailable"}
    return {"ok": True, "profile": p}


@router.post("/domain/knowledge/merge")
async def post_domain_knowledge_merge(
    body: KnowledgeMergeBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    sec = str(body.section or "tools")
    if sec == "other":
        sec = "other_notes"
    p = merge_knowledge(
        user_id=int(user.id),
        organization_id=int(user.organization_id),
        section=sec,
        items=body.items,
    )
    if p is None:
        return {"ok": False, "error": "database_unavailable"}
    return {"ok": True, "profile": p}


@router.get("/domain/templates")
async def get_domain_templates(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return get_action_templates(user_id=int(user.id), organization_id=int(user.organization_id))


@router.get("/domain/connectors")
async def get_domain_connectors(
    user: CurrentUser = Depends(require_permission("manage_business", "build_apps", "run_research")),
) -> dict[str, Any]:
    return list_domain_connectors(user_id=int(user.id))


@router.post("/domain/pipeline/run")
async def post_domain_pipeline(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
    max_execute: int = Query(1, ge=0, le=5),
    scan_first: bool = True,
) -> dict[str, Any]:
    return run_domain_opportunity_pipeline(
        user_id=int(user.id),
        organization_id=int(user.organization_id),
        role_name=str(user.role_name or "owner"),
        max_execute=int(max_execute),
        scan_first=bool(scan_first),
    )


@router.get("/domain/pnl")
async def get_domain_pnl(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
    hours: int = Query(7 * 24, ge=1, le=24 * 90),
) -> dict[str, Any]:
    return domain_pnl_summary(
        user_id=int(user.id), organization_id=int(user.organization_id), hours=int(hours)
    )


@router.post("/domain/pnl/record")
async def post_domain_pnl_record(
    body: RevenueEventBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    r = record_domain_revenue_event(
        user_id=int(user.id),
        organization_id=int(user.organization_id),
        event_type=body.event_type,
        amount=float(body.amount),
        note=body.note,
        domain=body.domain,
    )
    if r is None:
        return {"ok": False, "error": "database_unavailable"}
    return {**r, "ok": True}


@router.post("/domain/weekly/review")
async def post_domain_weekly_review(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return run_weekly_domain_strategy_review(
        user_id=int(user.id), organization_id=int(user.organization_id)
    )
