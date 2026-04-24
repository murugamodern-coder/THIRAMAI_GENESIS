"""Part D: stock assistant — watchlist, quotes, signals, portfolio (JWT).

Market data is best-effort third-party (yfinance; optional ``nsepython`` install). Portfolio endpoints are **paper /
simulated** trading only, not a licensed broker or investment advice.
"""

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
from services.stock_alert_service import (
    add_stock_price_alert_sync,
    delete_stock_price_alert_sync,
    list_stock_alerts_sync,
)
from services.stock_realtime_monitor import connect_to_market_data
from services.stock_signal_service import generate_intraday_signal
from services.governance_engine import log_execution, validate_action
from services.learning_engine import record_outcome, update_strategy_profiles

router = APIRouter(prefix="/stocks/assistant", tags=["Stock Assistant"])


def _uid(user: CurrentUser) -> int:
    uid = int(user.id)
    if uid <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    return uid


@router.post("/options/execute")
async def execute_options(
    symbol: str,
    expiry: str,
    strike: float,
    option_type: str,
    transaction_type: str,
    quantity: int = 1,
    mode: str = "paper",
    current_user: CurrentUser = Depends(get_current_user),
):
    from services.broker.options_executor import (
        OptionsOrder, OptionType, TransactionType, execute_options_order,
        INSTRUMENT_CONFIG
    )
    cfg = INSTRUMENT_CONFIG.get(symbol.upper(), {"lot_size": 50})
    try:
        ot = OptionType(option_type.upper())
        tx = TransactionType(transaction_type.upper())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid option params: {exc}") from exc
    order = OptionsOrder(
        symbol=symbol.upper(),
        expiry=expiry,
        strike=strike,
        option_type=ot,
        transaction_type=tx,
        quantity=quantity,
        lot_size=cfg["lot_size"],
    )
    result = await execute_options_order(order, user_id=_uid(current_user), mode=mode)
    return {
        "ok": result.success,
        "order_id": result.order_id,
        "broker": result.broker,
        "symbol": result.symbol,
        "message": result.message,
        "raw": result.raw_response,
    }


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
    trade_amount = float(body.quantity) * float(body.price_inr)
    check = validate_action(
        "trade_buy",
        {
            "user_id": _uid(user),
            "domain": "trading",
            "payload": {"symbol": body.symbol, "trade_amount": trade_amount},
        },
    )
    if not check.get("allowed"):
        log_execution(
            user_id=_uid(user),
            action_type="trade_buy",
            source="manual",
            payload_json={"symbol": body.symbol, "trade_amount": trade_amount},
            result_json={"blocked": True, "reason": check.get("reason") or "Governance blocked"},
            status="blocked",
            execution_id=f"trade_buy_{body.symbol.upper()}",
            reasoning_summary="Trade buy blocked by governance.",
            why_action_taken="Trade request exceeded configured guardrails.",
            data_influenced_json={"symbol": body.symbol, "trade_amount": trade_amount},
        )
        raise HTTPException(status_code=403, detail=check.get("reason") or "Governance blocked")
    out = add_stock_sync(
        _uid(user),
        body.symbol,
        body.quantity,
        body.price_inr,
        exchange_suffix=body.exchange_suffix,
        fees_inr=body.fees_inr,
    )
    if not out.get("ok"):
        log_execution(
            user_id=_uid(user),
            action_type="trade_buy",
            source="manual",
            payload_json={"symbol": body.symbol, "trade_amount": trade_amount},
            result_json=out,
            status="failed",
            execution_id=f"trade_buy_{body.symbol.upper()}",
            reasoning_summary="Trade buy failed in trading engine.",
            why_action_taken="Manual buy action attempted by user.",
            data_influenced_json={"symbol": body.symbol, "trade_amount": trade_amount},
        )
        raise HTTPException(status_code=400, detail=out.get("error") or "buy failed")
    log_execution(
        user_id=_uid(user),
        action_type="trade_buy",
        source="manual",
        payload_json={"symbol": body.symbol, "trade_amount": trade_amount},
        result_json=out,
        status="success",
        execution_id=f"trade_buy_{body.symbol.upper()}",
        reasoning_summary="Trade buy executed successfully.",
        why_action_taken="Manual user action accepted by governance and trading engine.",
        data_influenced_json={"symbol": body.symbol, "trade_amount": trade_amount},
    )
    record_outcome(
        user_id=_uid(user),
        organization_id=int(user.organization_id),
        source_type="trade",
        source_id=None,
        input_data={"symbol": body.symbol, "quantity": float(body.quantity), "price_inr": float(body.price_inr), "side": "buy"},
        outcome={"success": True, "profit_loss": 0.0, "note": "Trade buy executed"},
    )
    update_strategy_profiles(_uid(user))
    return out


@router.post("/portfolio/sell", summary="Paper sell (realized P&L)")
async def post_sell(body: TradeBody, user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    trade_amount = float(body.quantity) * float(body.price_inr)
    check = validate_action(
        "trade_sell",
        {
            "user_id": _uid(user),
            "domain": "trading",
            "payload": {"symbol": body.symbol, "trade_amount": trade_amount},
        },
    )
    if not check.get("allowed"):
        log_execution(
            user_id=_uid(user),
            action_type="trade_sell",
            source="manual",
            payload_json={"symbol": body.symbol, "trade_amount": trade_amount},
            result_json={"blocked": True, "reason": check.get("reason") or "Governance blocked"},
            status="blocked",
            execution_id=f"trade_sell_{body.symbol.upper()}",
            reasoning_summary="Trade sell blocked by governance.",
            why_action_taken="Trade request exceeded configured guardrails.",
            data_influenced_json={"symbol": body.symbol, "trade_amount": trade_amount},
        )
        raise HTTPException(status_code=403, detail=check.get("reason") or "Governance blocked")
    out = sell_stock_sync(
        _uid(user),
        body.symbol,
        body.quantity,
        body.price_inr,
        exchange_suffix=body.exchange_suffix,
        fees_inr=body.fees_inr,
    )
    if not out.get("ok"):
        log_execution(
            user_id=_uid(user),
            action_type="trade_sell",
            source="manual",
            payload_json={"symbol": body.symbol, "trade_amount": trade_amount},
            result_json=out,
            status="failed",
            execution_id=f"trade_sell_{body.symbol.upper()}",
            reasoning_summary="Trade sell failed in trading engine.",
            why_action_taken="Manual sell action attempted by user.",
            data_influenced_json={"symbol": body.symbol, "trade_amount": trade_amount},
        )
        raise HTTPException(status_code=400, detail=out.get("error") or "sell failed")
    realized = float(out.get("realized_pnl_inr") or out.get("realized_pnl") or 0)
    log_execution(
        user_id=_uid(user),
        action_type="trade_sell",
        source="manual",
        payload_json={"symbol": body.symbol, "trade_amount": trade_amount},
        result_json={**out, "realized_pnl": realized},
        status="success",
        execution_id=f"trade_sell_{body.symbol.upper()}",
        reasoning_summary="Trade sell executed successfully.",
        why_action_taken="Manual user action accepted by governance and trading engine.",
        data_influenced_json={"symbol": body.symbol, "trade_amount": trade_amount, "realized_pnl": realized},
    )
    record_outcome(
        user_id=_uid(user),
        organization_id=int(user.organization_id),
        source_type="trade",
        source_id=None,
        input_data={"symbol": body.symbol, "quantity": float(body.quantity), "price_inr": float(body.price_inr), "side": "sell"},
        outcome={"success": realized >= 0, "profit_loss": realized, "note": "Trade sell executed"},
    )
    update_strategy_profiles(_uid(user))
    return out


@router.get("/morning-brief", summary="Indices + opportunities + sentiment")
async def get_morning_brief(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    return morning_market_brief_sync(user_id=_uid(user))


@router.get("/realtime/status", summary="Realtime monitor backend mode (polling vs configured WS)")
async def get_realtime_status(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    _ = user
    return {"ok": True, "mode": connect_to_market_data()}


@router.get("/alerts", summary="List active price alerts")
async def list_alerts(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    return {"ok": True, "items": list_stock_alerts_sync(_uid(user))}


class StockAlertCreateBody(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)
    condition: str = Field(..., min_length=3, max_length=24, description="above | below | percent_change")
    price: Decimal | None = Field(None, description="Threshold for above/below")
    action: str = Field("notify", max_length=32)
    exchange_suffix: str = Field("NS", max_length=8)
    reference_price: Decimal | None = None
    percent_threshold: Decimal | None = Field(None, description="Required for percent_change (percent points)")


@router.post("/alerts", summary="Create price / percent alert")
async def create_alert(body: StockAlertCreateBody, user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    out = add_stock_price_alert_sync(
        _uid(user),
        symbol=body.symbol,
        condition=body.condition,
        price=body.price,
        action=body.action,
        exchange_suffix=body.exchange_suffix,
        reference_price=body.reference_price,
        percent_threshold=body.percent_threshold,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "create_failed")
    return out


@router.delete("/alerts/{alert_id}", summary="Deactivate alert")
async def remove_alert(alert_id: int, user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    out = delete_stock_price_alert_sync(_uid(user), int(alert_id))
    if not out.get("ok"):
        raise HTTPException(status_code=404, detail=out.get("error") or "not_found")
    return out
