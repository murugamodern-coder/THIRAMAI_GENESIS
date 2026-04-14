"""Persisted price / percent alerts for real-time stock monitor (Upgrade 4)."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.database import get_session_factory
from core.db.models import StockPriceAlert

_log = logging.getLogger("thiramai.stock_alerts")


def _factory() -> sessionmaker[Session] | None:
    return get_session_factory()  # type: ignore[return-value]


def list_stock_alerts_sync(user_id: int) -> list[dict[str, Any]]:
    uid = int(user_id)
    if uid <= 0:
        return []
    fac = _factory()
    if fac is None:
        return []
    with fac() as session:
        rows = session.scalars(
            select(StockPriceAlert)
            .where(StockPriceAlert.user_id == uid, StockPriceAlert.is_active.is_(True))
            .order_by(StockPriceAlert.created_at.desc())
            .limit(50)
        ).all()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": int(r.id),
                "symbol": r.symbol,
                "exchange_suffix": r.exchange_suffix or "NS",
                "condition": r.condition_type,
                "price_threshold": str(r.price_threshold) if r.price_threshold is not None else None,
                "reference_price": str(r.reference_price) if r.reference_price is not None else None,
                "percent_threshold": str(r.percent_threshold) if r.percent_threshold is not None else None,
                "action": r.action,
                "is_active": bool(r.is_active),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return out


def add_stock_price_alert_sync(
    user_id: int,
    *,
    symbol: str,
    condition: str,
    price: float | Decimal | str | None = None,
    action: str = "notify",
    exchange_suffix: str = "NS",
    reference_price: float | Decimal | str | None = None,
    percent_threshold: float | Decimal | str | None = None,
) -> dict[str, Any]:
    uid = int(user_id)
    sym = (symbol or "").strip().upper().replace(".NS", "").replace(".BO", "")
    cond = (condition or "").strip().lower()
    act = (action or "notify").strip().lower()[:32]
    if uid <= 0 or not sym:
        return {"ok": False, "error": "invalid user or symbol"}
    if cond not in ("above", "below", "percent_change"):
        return {"ok": False, "error": "condition must be above, below, or percent_change"}
    if act not in ("notify", "suggest", "confirm_sell"):
        act = "notify"
    ex = (exchange_suffix or "NS").strip().upper()[:8]

    pt: Decimal | None = None
    refp: Decimal | None = None
    pct_thr: Decimal | None = None
    try:
        if cond in ("above", "below") and price is not None:
            pt = Decimal(str(price)).quantize(Decimal("0.0001"))
        if cond == "percent_change":
            if percent_threshold is not None:
                pct_thr = Decimal(str(percent_threshold)).quantize(Decimal("0.01"))
            if reference_price is not None:
                refp = Decimal(str(reference_price)).quantize(Decimal("0.0001"))
    except Exception:
        return {"ok": False, "error": "invalid numeric fields"}

    if cond in ("above", "below") and (pt is None or pt <= 0):
        return {"ok": False, "error": "positive price required for above/below"}
    if cond == "percent_change" and (pct_thr is None or pct_thr <= 0):
        return {"ok": False, "error": "percent_threshold required for percent_change"}
    if cond == "percent_change" and refp is None:
        from services.stock_market_data_service import get_live_price

        q = get_live_price(sym, exchange_suffix=ex)
        if not q.get("ok"):
            return {"ok": False, "error": "could not resolve reference price; set reference_price explicitly"}
        try:
            refp = Decimal(str(q.get("last"))).quantize(Decimal("0.0001"))
        except Exception:
            return {"ok": False, "error": "invalid live reference price"}

    fac = _factory()
    if fac is None:
        return {"ok": False, "error": "database not configured"}

    with fac() as session:
        with session.begin():
            row = StockPriceAlert(
                user_id=uid,
                symbol=sym,
                exchange_suffix=ex,
                condition_type=cond,
                price_threshold=pt,
                reference_price=refp,
                percent_threshold=pct_thr,
                action=act,
                is_active=True,
            )
            session.add(row)
            session.flush()
            rid = int(row.id)
    return {"ok": True, "id": rid}


def delete_stock_price_alert_sync(user_id: int, alert_id: int) -> dict[str, Any]:
    uid = int(user_id)
    aid = int(alert_id)
    if uid <= 0 or aid <= 0:
        return {"ok": False, "error": "invalid ids"}
    fac = _factory()
    if fac is None:
        return {"ok": False, "error": "database not configured"}
    with fac() as session:
        with session.begin():
            row = session.get(StockPriceAlert, aid)
            if row is None or int(row.user_id) != uid:
                return {"ok": False, "error": "not found"}
            row.is_active = False
    return {"ok": True}
