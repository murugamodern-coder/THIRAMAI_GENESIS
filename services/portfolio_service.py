"""Paper equity portfolio, daily realized P&L, and daily loss guard (Part D)."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from core.database import get_session_factory
from core.db.models import EquityPortfolioPosition, EquityPortfolioTransaction, StockWatchlistEntry

_log = logging.getLogger("thiramai.portfolio")

_IST = ZoneInfo("Asia/Kolkata")


def _factory() -> sessionmaker[Session] | None:
    return get_session_factory()  # type: ignore[return-value]


def _max_daily_loss_inr() -> Decimal:
    try:
        return Decimal(str((os.getenv("THIRAMAI_MAX_DAILY_LOSS_INR") or "2000").strip()))
    except Exception:
        return Decimal("2000")


def _ist_day_start_utc() -> datetime:
    now_ist = datetime.now(_IST)
    start_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_ist.astimezone(timezone.utc)


def _risk_block_redis_key(user_id: int) -> str:
    d = datetime.now(_IST).date().isoformat()
    return f"thiramai:equity:risk_block:{int(user_id)}:{d}"


def _seconds_until_ist_midnight() -> int:
    now = datetime.now(_IST)
    nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    sec = int((nxt - now).total_seconds())
    return max(60, min(sec, 86400))


def _redis_set_block(user_id: int) -> None:
    try:
        from services.worker_heartbeat import redis_client

        r = redis_client()
        if not r:
            return
        r.setex(_risk_block_redis_key(user_id), _seconds_until_ist_midnight(), "1")
    except Exception as exc:
        _log.debug("redis risk block: %s", exc)


def enforce_equity_risk_block_if_needed_sync(user_id: int) -> bool:
    """If realized P&L today is at or below -limit, set Redis block for the IST session."""
    uid = int(user_id)
    if uid <= 0:
        return False
    lim = _max_daily_loss_inr()
    pnl = daily_equity_pnl_inr_sync(uid)
    if pnl <= -lim:
        _redis_set_block(uid)
        return True
    return False


def is_equity_risk_blocked_sync(user_id: int) -> bool:
    uid = int(user_id)
    if uid <= 0:
        return False
    try:
        from services.worker_heartbeat import redis_client

        r = redis_client()
        if r and r.get(_risk_block_redis_key(uid)):
            return True
    except Exception as exc:
        _log.debug("redis risk read: %s", exc)
    lim = _max_daily_loss_inr()
    return daily_equity_pnl_inr_sync(uid) <= -lim


def daily_equity_pnl_inr_sync(user_id: int) -> Decimal:
    """Sum of realized P&L from sells today (IST calendar day)."""
    uid = int(user_id)
    if uid <= 0:
        return Decimal("0")
    factory = _factory()
    if factory is None:
        return Decimal("0")
    start = _ist_day_start_utc()
    with factory() as session:
        total = session.execute(
            select(func.coalesce(func.sum(EquityPortfolioTransaction.realized_pnl_inr), 0)).where(
                EquityPortfolioTransaction.user_id == uid,
                EquityPortfolioTransaction.side == "sell",
                EquityPortfolioTransaction.created_at >= start,
            )
        ).scalar()
    try:
        return Decimal(str(total or 0)).quantize(Decimal("0.01"))
    except Exception:
        return Decimal("0")


def _norm_symbol(symbol: str) -> str:
    return (symbol or "").strip().upper().replace(".NS", "").replace(".BO", "")


def add_stock_sync(
    user_id: int,
    symbol: str,
    quantity: Decimal | float | str,
    price_inr: Decimal | float | str,
    *,
    exchange_suffix: str = "NS",
    fees_inr: Decimal | float | str = Decimal("0"),
) -> dict[str, Any]:
    uid = int(user_id)
    sym = _norm_symbol(symbol)
    if uid <= 0 or not sym:
        return {"ok": False, "error": "invalid user or symbol"}
    try:
        qty = Decimal(str(quantity))
        px = Decimal(str(price_inr)).quantize(Decimal("0.0001"))
        fees = Decimal(str(fees_inr)).quantize(Decimal("0.01"))
    except Exception:
        return {"ok": False, "error": "invalid quantity or price"}
    if qty <= 0 or px <= 0:
        return {"ok": False, "error": "quantity and price must be positive"}
    ex = (exchange_suffix or "NS").strip().upper()[:8]

    factory = _factory()
    if factory is None:
        return {"ok": False, "error": "database not configured"}

    with factory() as session:
        with session.begin():
            row = session.execute(
                select(EquityPortfolioPosition).where(
                    EquityPortfolioPosition.user_id == uid,
                    EquityPortfolioPosition.symbol == sym,
                    EquityPortfolioPosition.exchange_suffix == ex,
                ).limit(1)
            ).scalar_one_or_none()
            old_q = Decimal("0")
            old_avg = Decimal("0")
            if row:
                old_q = Decimal(str(row.quantity or 0))
                old_avg = Decimal(str(row.avg_buy_price_inr or 0))
            new_q = old_q + qty
            if new_q <= 0:
                return {"ok": False, "error": "invalid resulting quantity"}
            new_avg = ((old_q * old_avg) + (qty * px)) / new_q if new_q else px
            if row:
                row.quantity = new_q
                row.avg_buy_price_inr = new_avg.quantize(Decimal("0.0001"))
            else:
                row = EquityPortfolioPosition(
                    user_id=uid,
                    symbol=sym,
                    exchange_suffix=ex,
                    quantity=new_q,
                    avg_buy_price_inr=new_avg.quantize(Decimal("0.0001")),
                )
                session.add(row)
            session.add(
                EquityPortfolioTransaction(
                    user_id=uid,
                    symbol=sym,
                    exchange_suffix=ex,
                    side="buy",
                    quantity=qty,
                    price_inr=px,
                    fees_inr=fees,
                    realized_pnl_inr=None,
                )
            )
    return {"ok": True, "symbol": sym, "quantity": str(new_q), "avg_buy_price_inr": str(new_avg.quantize(Decimal("0.0001")))}


def sell_stock_sync(
    user_id: int,
    symbol: str,
    quantity: Decimal | float | str,
    price_inr: Decimal | float | str,
    *,
    exchange_suffix: str = "NS",
    fees_inr: Decimal | float | str = Decimal("0"),
) -> dict[str, Any]:
    uid = int(user_id)
    sym = _norm_symbol(symbol)
    if uid <= 0 or not sym:
        return {"ok": False, "error": "invalid user or symbol"}
    try:
        qty = Decimal(str(quantity))
        px = Decimal(str(price_inr)).quantize(Decimal("0.0001"))
        fees = Decimal(str(fees_inr)).quantize(Decimal("0.01"))
    except Exception:
        return {"ok": False, "error": "invalid quantity or price"}
    if qty <= 0 or px <= 0:
        return {"ok": False, "error": "quantity and price must be positive"}
    ex = (exchange_suffix or "NS").strip().upper()[:8]

    factory = _factory()
    if factory is None:
        return {"ok": False, "error": "database not configured"}

    with factory() as session:
        with session.begin():
            row = session.execute(
                select(EquityPortfolioPosition).where(
                    EquityPortfolioPosition.user_id == uid,
                    EquityPortfolioPosition.symbol == sym,
                    EquityPortfolioPosition.exchange_suffix == ex,
                ).limit(1)
            ).scalar_one_or_none()
            if row is None:
                return {"ok": False, "error": "no position"}
            old_q = Decimal(str(row.quantity or 0))
            if qty > old_q:
                return {"ok": False, "error": "insufficient quantity"}
            avg = Decimal(str(row.avg_buy_price_inr or 0))
            realized = ((px - avg) * qty) - fees
            new_q = old_q - qty
            row.quantity = new_q
            if new_q <= 0:
                row.quantity = Decimal("0")
                row.avg_buy_price_inr = Decimal("0")
            session.add(
                EquityPortfolioTransaction(
                    user_id=uid,
                    symbol=sym,
                    exchange_suffix=ex,
                    side="sell",
                    quantity=qty,
                    price_inr=px,
                    fees_inr=fees,
                    realized_pnl_inr=realized.quantize(Decimal("0.01")),
                )
            )
    enforce_equity_risk_block_if_needed_sync(uid)
    return {
        "ok": True,
        "symbol": sym,
        "quantity_sold": str(qty),
        "realized_pnl_inr": str(realized.quantize(Decimal("0.01"))),
        "remaining_quantity": str(new_q.quantize(Decimal("0.000001"))),
    }


def get_portfolio_summary_sync(user_id: int) -> dict[str, Any]:
    uid = int(user_id)
    if uid <= 0:
        return {"ok": False, "error": "invalid user"}
    factory = _factory()
    if factory is None:
        return {"ok": False, "error": "database not configured"}

    from services.stock_market_data_service import get_live_price

    with factory() as session:
        rows = list(
            session.scalars(
                select(EquityPortfolioPosition)
                .where(EquityPortfolioPosition.user_id == uid)
                .where(EquityPortfolioPosition.quantity > 0)
            ).all()
        )

    positions_out: list[dict[str, Any]] = []
    total_value = Decimal("0")
    total_cost = Decimal("0")
    for r in rows:
        sym = str(r.symbol)
        ex = str(r.exchange_suffix or "NS")
        qty = Decimal(str(r.quantity or 0))
        avg = Decimal(str(r.avg_buy_price_inr or 0))
        cost = (qty * avg).quantize(Decimal("0.01"))
        qpx = get_live_price(sym, exchange_suffix=ex)
        last = Decimal(str(qpx["last"])) if qpx.get("ok") else avg
        value = (qty * last).quantize(Decimal("0.01"))
        pnl = (value - cost).quantize(Decimal("0.01"))
        total_value += value
        total_cost += cost
        positions_out.append(
            {
                "symbol": sym,
                "exchange_suffix": ex,
                "quantity": str(qty),
                "avg_buy_price_inr": str(avg),
                "last_price_inr": str(last) if qpx.get("ok") else None,
                "current_value_inr": str(value),
                "cost_basis_inr": str(cost),
                "pnl_inr": str(pnl),
                "quote_ok": bool(qpx.get("ok")),
            }
        )

    total_pnl = (total_value - total_cost).quantize(Decimal("0.01"))
    return {
        "ok": True,
        "positions": positions_out,
        "total_current_value_inr": str(total_value.quantize(Decimal("0.01"))),
        "total_cost_basis_inr": str(total_cost.quantize(Decimal("0.01"))),
        "total_pnl_inr": str(total_pnl),
        "daily_realized_pnl_inr": str(daily_equity_pnl_inr_sync(uid)),
        "risk_blocked": is_equity_risk_blocked_sync(uid),
        "max_daily_loss_inr": str(_max_daily_loss_inr()),
    }


def add_to_watchlist_sync(user_id: int, symbol: str, *, exchange_suffix: str = "NS") -> dict[str, Any]:
    uid = int(user_id)
    sym = _norm_symbol(symbol)
    if uid <= 0 or not sym:
        return {"ok": False, "error": "invalid user or symbol"}
    ex = (exchange_suffix or "NS").strip().upper()[:8]
    factory = _factory()
    if factory is None:
        return {"ok": False, "error": "database not configured"}
    with factory() as session:
        with session.begin():
            existing = session.execute(
                select(StockWatchlistEntry).where(StockWatchlistEntry.user_id == uid, StockWatchlistEntry.symbol == sym).limit(1)
            ).scalar_one_or_none()
            if existing:
                existing.exchange_suffix = ex
                return {"ok": True, "symbol": sym, "updated": True}
            session.add(StockWatchlistEntry(user_id=uid, symbol=sym, exchange_suffix=ex))
    return {"ok": True, "symbol": sym, "created": True}


def list_watchlist_symbols_sync(user_id: int, *, limit: int = 24) -> list[str]:
    uid = int(user_id)
    if uid <= 0:
        return []
    factory = _factory()
    if factory is None:
        return []
    lim = max(1, min(int(limit), 48))
    with factory() as session:
        rows = session.scalars(
            select(StockWatchlistEntry.symbol)
            .where(StockWatchlistEntry.user_id == uid)
            .order_by(StockWatchlistEntry.created_at.desc())
            .limit(lim)
        ).all()
    return [str(s) for s in rows if s]
