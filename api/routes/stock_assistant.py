"""Part D: stock assistant — watchlist, quotes, signals, portfolio (JWT)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, get_current_user
from services.market_brief_service import morning_market_brief_sync
from services.portfolio_service import (
    add_stock_sync,
    add_to_watchlist_sync,
    get_portfolio_summary_sync,
    list_watchlist_symbols_sync,
    sell_stock_sync,
)
from services.stock_indicator_service import analyze_indicators
from services.stock_market_data_service import get_live_price
from services.stock_signal_service import generate_intraday_signal

router = APIRouter(prefix="/stocks/assistant", tags=["Stock Assistant"])


def _uid(user: CurrentUser) -> int:
    uid = int(user.id)
    if uid <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    return uid


@router.get("/watchlist", summary="List watchlist symbols")
async def get_watchlist(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    return {"ok": True, "symbols": list_watchlist_symbols_sync(uid)}


class WatchlistBody(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)
    exchange_suffix: str = Field("NS", max_length=8)


@router.post("/watchlist", summary="Add symbol to watchlist")
async def post_watchlist(body: WatchlistBody, user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    return add_to_watchlist_sync(_uid(user), body.symbol, exchange_suffix=body.exchange_suffix)


@router.get("/quote/{symbol}", summary="Live quote (cached)")
async def get_quote(symbol: str, user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    _ = user
    return get_live_price(symbol.strip().upper(), exchange_suffix="NS")


@router.get("/analyze/{symbol}", summary="RSI / MACD / EMA / Bollinger bundle")
async def get_analyze(symbol: str, user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    _ = user
    return analyze_indicators(symbol.strip().upper(), interval="5m", exchange_suffix="NS")


@router.get("/signal/{symbol}", summary="Rule-based intraday-style signal")
async def get_signal(symbol: str, user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    return generate_intraday_signal(symbol.strip().upper(), user_id=_uid(user), exchange_suffix="NS")


@router.get("/portfolio", summary="Portfolio summary + P&L")
async def get_portfolio(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    return get_portfolio_summary_sync(_uid(user))


class TradeBody(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)
    quantity: Decimal = Field(..., gt=0)
    price_inr: Decimal = Field(..., gt=0)
    exchange_suffix: str = Field("NS", max_length=8)
    fees_inr: Decimal = Field(Decimal("0"), ge=0)


@router.post("/portfolio/buy", summary="Paper buy (increases position)")
async def post_buy(body: TradeBody, user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    out = add_stock_sync(
        _uid(user),
        body.symbol,
        body.quantity,
        body.price_inr,
        exchange_suffix=body.exchange_suffix,
        fees_inr=body.fees_inr,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "buy failed")
    return out


@router.post("/portfolio/sell", summary="Paper sell (realized P&L)")
async def post_sell(body: TradeBody, user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    out = sell_stock_sync(
        _uid(user),
        body.symbol,
        body.quantity,
        body.price_inr,
        exchange_suffix=body.exchange_suffix,
        fees_inr=body.fees_inr,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "sell failed")
    return out


@router.get("/morning-brief", summary="Indices + opportunities + sentiment")
async def get_morning_brief(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    return morning_market_brief_sync(user_id=_uid(user))
