"""Market timing: trends, momentum, entry/exit, confidence (predictive + feedback)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.dependencies import CurrentUser, require_permission
from services.market_timing_engine import market_timing_pack, timing_from_custom_series

router = APIRouter(tags=["Market timing"])


class MarketTimingAnalyzeBody(BaseModel):
    values: list[float] | None = None
    oldest_first: bool = False


@router.get("/market-timing/summary")
async def get_market_timing_summary(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return market_timing_pack(int(user.id), values=None)


@router.post("/market-timing/analyze")
async def post_market_timing_analyze(
    body: MarketTimingAnalyzeBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    if not body.values:
        return market_timing_pack(int(user.id), values=None)
    return timing_from_custom_series(int(user.id), body.values, oldest_first=bool(body.oldest_first))
