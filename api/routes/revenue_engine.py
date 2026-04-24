"""Revenue engine APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.opportunity_engine import list_opportunities
from services.revenue_engine import auto_reinvest_profit, record_real_income, revenue_snapshot, scale_capital_allocation

router = APIRouter(tags=["Revenue Engine"])


class RevenueRecordBody(BaseModel):
    amount: float = Field(..., ge=0)
    source: str = Field("manual_revenue", max_length=64)
    note: str = Field("", max_length=500)


@router.post("/revenue/record")
async def post_revenue_record(
    body: RevenueRecordBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock")),
) -> dict[str, Any]:
    return record_real_income(
        user_id=int(user.id),
        organization_id=int(user.organization_id),
        amount=float(body.amount),
        source=body.source,
        note=body.note,
    )


@router.get("/revenue/snapshot")
async def get_revenue_snapshot(
    hours: int = 24 * 7,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock")),
) -> dict[str, Any]:
    return revenue_snapshot(int(user.id), int(hours))


@router.post("/revenue/reinvest")
async def post_revenue_reinvest(
    ratio: float = 0.5,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock")),
) -> dict[str, Any]:
    return auto_reinvest_profit(int(user.id), int(user.organization_id), float(ratio))


@router.get("/revenue/scale-allocation")
async def get_revenue_scale_allocation(
    base_capital: float = 50000.0,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock")),
) -> dict[str, Any]:
    opportunities = list_opportunities(int(user.id), limit=120)
    return scale_capital_allocation(int(user.id), opportunities, float(base_capital))
