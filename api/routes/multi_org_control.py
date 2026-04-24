"""Multi-organization control APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from api.dependencies import CurrentUser, require_permission
from services.multi_org_control_engine import list_user_organizations, separate_execution_plan, shared_intelligence_context

router = APIRouter(tags=["Multi Org Control"])


@router.get("/multi-org/organizations")
async def get_multi_org_organizations(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return {"ok": True, "items": list_user_organizations(int(user.id))}


@router.get("/multi-org/shared-intelligence")
async def get_multi_org_shared_intelligence(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return shared_intelligence_context(int(user.id))


@router.get("/multi-org/execution-plan")
async def get_multi_org_execution_plan(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return separate_execution_plan(int(user.id))
