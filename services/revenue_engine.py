"""Revenue engine: track realized income and auto-reinvestment signals."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import LearningLog, Opportunity, OpportunityProfitLog
from services.money_loop_engine import upsert_money_loop_config
from services.profit_optimizer import allocate_capital


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def record_real_income(
    *,
    user_id: int,
    organization_id: int,
    amount: float,
    source: str = "manual_revenue",
    note: str = "",
) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        return {"ok": False, "error": "Database unavailable"}
    amt = float(amount or 0)
    with factory() as session:
        row = LearningLog(
            resolved_by_user_id=int(user_id),
            organization_id=int(organization_id),
            source_type="revenue_engine",
            source_id=None,
            input_data_json={"source": str(source or "manual_revenue"), "recorded_at": _now().isoformat()},
            outcome_json={"real_income": amt, "note": str(note or "")[:500]},
            success=bool(amt >= 0),
            outcome="success" if amt >= 0 else "failure",
            action_type="record_real_income",
            lesson_summary="Real income recorded for revenue engine.",
            context={"source": source},
            result={"amount": amt},
        )
        session.add(row)
        session.commit()
        rid = int(row.id)
    return {"ok": True, "id": rid, "amount": amt}


def revenue_snapshot(user_id: int, hours: int = 24 * 7) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        return {"ok": True, "real_income": 0.0, "opportunity_profit": 0.0, "total": 0.0}
    since = _now() - timedelta(hours=max(1, int(hours)))
    with factory() as session:
        rev_rows = (
            session.execute(
                select(LearningLog)
                .where(
                    LearningLog.resolved_by_user_id == int(user_id),
                    LearningLog.source_type == "revenue_engine",
                    LearningLog.created_at >= since,
                )
                .order_by(LearningLog.created_at.desc())
            )
            .scalars()
            .all()
        )
        opp_rows = (
            session.execute(
                select(OpportunityProfitLog, Opportunity)
                .join(Opportunity, Opportunity.id == OpportunityProfitLog.opportunity_id)
                .where(Opportunity.user_id == int(user_id), OpportunityProfitLog.created_at >= since)
            )
            .all()
        )
    real_income = 0.0
    for r in rev_rows:
        out = r.outcome_json or {}
        real_income += float(out.get("real_income") or 0)
    opp_profit = 0.0
    for pl, _ in opp_rows:
        opp_profit += float(getattr(pl, "profit_loss_amount", 0) or 0)
    total = real_income + opp_profit
    return {
        "ok": True,
        "window_hours": int(hours),
        "real_income": round(real_income, 2),
        "opportunity_profit": round(opp_profit, 2),
        "total": round(total, 2),
    }


def auto_reinvest_profit(user_id: int, organization_id: int, reinvest_ratio: float = 0.5) -> dict[str, Any]:
    snap = revenue_snapshot(int(user_id), 24 * 7)
    profit = float(snap.get("total") or 0)
    ratio = max(0.0, min(float(reinvest_ratio or 0), 1.0))
    reinvest_amount = max(0.0, profit * ratio)
    cfg = upsert_money_loop_config(
        user_id=int(user_id),
        enabled=True,
        max_daily_capital=max(1000.0, reinvest_amount),
        optimizer_enabled=True,
    )
    return {
        "ok": True,
        "profit_window_total": round(profit, 2),
        "reinvest_ratio": ratio,
        "reinvest_amount": round(reinvest_amount, 2),
        "money_loop_config": cfg or {},
    }


def scale_capital_allocation(user_id: int, opportunities: list[dict[str, Any]], base_capital: float) -> dict[str, Any]:
    snap = revenue_snapshot(int(user_id), 24 * 7)
    growth_boost = max(0.0, float(snap.get("total") or 0) * 0.2)
    scaled_capital = max(0.0, float(base_capital or 0) + growth_boost)
    alloc = allocate_capital(opportunities, total_capital=scaled_capital, user_id=int(user_id))
    return {
        "ok": True,
        "base_capital": float(base_capital or 0),
        "growth_boost": round(growth_boost, 2),
        "scaled_capital": round(scaled_capital, 2),
        "allocations": alloc,
    }
