"""Opportunity engine APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import CurrentUser, require_permission
from services.opportunity_engine import (
    approve_opportunity,
    best_opportunity_today,
    execute_opportunity,
    list_opportunities,
    scan_all_opportunities,
)
from services.async_task_queue import enqueue_task

router = APIRouter(tags=["Opportunities"])


@router.get("/opportunities")
async def get_opportunities(
    limit: int = Query(100, ge=1, le=300),
    rescan: bool = Query(False),
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    if rescan:
        queued = enqueue_task(
            "opportunity_scan",
            {"user_id": int(user.id), "organization_id": int(user.organization_id)},
        )
        if not queued.get("queued"):
            scan_all_opportunities(user_id=int(user.id), organization_id=int(user.organization_id))
    return {
        "ok": True,
        "items": list_opportunities(user_id=int(user.id), limit=limit),
        "best_today": best_opportunity_today(user_id=int(user.id)),
    }


@router.post("/opportunities/{opportunity_id}/approve")
async def post_approve_opportunity(
    opportunity_id: int,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock")),
) -> dict[str, Any]:
    out = approve_opportunity(user_id=int(user.id), opportunity_id=int(opportunity_id))
    if not out.get("ok"):
        raise HTTPException(status_code=404, detail=out.get("error") or "Approve failed")
    return out


@router.post("/opportunities/{opportunity_id}/execute")
async def post_execute_opportunity(
    opportunity_id: int,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "build_apps")),
) -> dict[str, Any]:
    out = execute_opportunity(
        user_id=int(user.id),
        organization_id=int(user.organization_id),
        role_name=str(user.role_name or ""),
        opportunity_id=int(opportunity_id),
    )
    if not out.get("ok"):
        raise HTTPException(status_code=404, detail=out.get("error") or "Execute failed")
    return out
