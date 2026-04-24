"""Predictive intelligence engine (trend + anomaly + success probability)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory as _get_session_factory
from core.db.models import LearningLog, Opportunity, OpportunityProfitLog
from services.feedback_engine import adjust_model_weights


def get_session_factory():
    """Compatibility wrapper for tests and monkeypatching."""
    return _get_session_factory()

_ORIGINAL_GET_SESSION_FACTORY = get_session_factory


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _moving_avg(values: list[float], n: int) -> float:
    if not values:
        return 0.0
    k = max(1, min(int(n), len(values)))
    return float(sum(values[:k]) / k)


def _forecast_numeric(values: list[float]) -> dict[str, Any]:
    """
    Small numeric forecaster used by SRE sanity tests.
    Values are expected newest-first.
    """
    nums = [float(x) for x in list(values or [])]
    if not nums:
        return {"method": "no_data", "next_value": 0.0, "confidence": 0.0}
    if len(nums) < 3:
        return {
            "method": "moving_average",
            "next_value": round(sum(nums) / float(len(nums)), 2),
            "confidence": 0.5,
        }
    ma_short = _moving_avg(nums, 3)
    ma_long = _moving_avg(nums, min(8, len(nums)))
    blended = (0.65 * ma_short) + (0.35 * ma_long)
    return {
        "method": "blend_ma_linear_short",
        "next_value": round(blended, 2),
        "confidence": 0.62,
    }


def _recent_profit_series(user_id: int, hours: int = 72) -> list[float]:
    factory = _session_factory_or_none()
    if factory is None:
        return []
    since = _now() - timedelta(hours=max(1, int(hours)))
    with factory() as session:
        rows = (
            session.execute(
                select(OpportunityProfitLog, Opportunity)
                .join(Opportunity, Opportunity.id == OpportunityProfitLog.opportunity_id)
                .where(Opportunity.user_id == int(user_id), OpportunityProfitLog.created_at >= since)
                .order_by(OpportunityProfitLog.created_at.desc(), OpportunityProfitLog.id.desc())
            )
            .all()
        )
        return [float(getattr(pl, "profit_loss_amount", 0) or 0) for pl, _opp in rows]


def recent_profit_value_series(user_id: int, hours: int = 120) -> list[float]:
    """Newest-first profit outcomes for time-series / timing (market timing engine, charts)."""
    return _recent_profit_series(int(user_id), hours=max(1, int(hours)))


def forecast_profit_trend(user_id: int) -> dict[str, Any]:
    values = _recent_profit_series(int(user_id), hours=96)
    ma_short = _moving_avg(values, 5)
    ma_long = _moving_avg(values, 20)
    trend = "up" if ma_short >= ma_long else "down"
    confidence = 0.65 + min(abs(ma_short - ma_long) / max(abs(ma_long) + 1.0, 1.0), 0.25)
    return {
        "trend": trend,
        "ma_short": round(ma_short, 2),
        "ma_long": round(ma_long, 2),
        "confidence": round(min(max(confidence, 0.1), 0.98), 3),
        "recommended_action": "Scale selectively" if trend == "up" else "Reduce exposure",
    }


def predict_risk_spike(user_id: int) -> dict[str, Any]:
    values = _recent_profit_series(int(user_id), hours=72)
    if not values:
        return {"risk_level": "medium", "probability": 0.5, "reason": "Insufficient recent outcomes"}
    negatives = [abs(v) for v in values if v < 0]
    volatility = sum(abs(v) for v in values[:15]) / max(len(values[:15]), 1)
    neg_ratio = len(negatives) / max(len(values), 1)
    spike_prob = min(0.95, 0.2 + (neg_ratio * 0.55) + min(volatility / 50000.0, 0.2))
    if spike_prob >= 0.7:
        level = "high"
    elif spike_prob >= 0.45:
        level = "medium"
    else:
        level = "low"
    return {
        "risk_level": level,
        "probability": round(spike_prob, 3),
        "reason": "Based on negative-outcome ratio and short-term volatility.",
    }


def detect_market_shift(user_id: int) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        return {"shift_detected": False, "confidence": 0.0, "signal": "no_data"}
    with factory() as session:
        rows = (
            session.execute(
                select(Opportunity)
                .where(Opportunity.user_id == int(user_id))
                .order_by(Opportunity.created_at.desc(), Opportunity.id.desc())
                .limit(40)
            )
            .scalars()
            .all()
        )
    if not rows:
        return {"shift_detected": False, "confidence": 0.0, "signal": "no_data"}
    recent = rows[:15]
    older = rows[15:40]
    r_profit = sum(float(r.expected_profit or 0) for r in recent) / max(len(recent), 1)
    o_profit = sum(float(r.expected_profit or 0) for r in older) / max(len(older), 1) if older else r_profit
    change = (r_profit - o_profit) / max(abs(o_profit) + 1.0, 1.0)
    shift = abs(change) > 0.25
    return {
        "shift_detected": bool(shift),
        "confidence": round(min(0.95, abs(change)), 3),
        "signal": "bullish_shift" if change > 0 else "defensive_shift",
        "change_ratio": round(change, 3),
    }


def predict_opportunity_success(user_id: int, opportunity_id: int | None = None) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        return {"success_probability": 0.5, "confidence": 0.4}
    with factory() as session:
        q = select(LearningLog).where(LearningLog.user_id == int(user_id), LearningLog.source_type == "opportunity")
        if opportunity_id:
            q = q.where(LearningLog.source_id == int(opportunity_id))
        rows = session.execute(q.order_by(LearningLog.created_at.desc(), LearningLog.id.desc()).limit(50)).scalars().all()
    if not rows:
        return {"success_probability": 0.55, "confidence": 0.45}
    wins = 0.0
    for row in rows:
        if row.success is True:
            wins += 1
        elif row.success is None:
            out = row.outcome_json or {}
            pnl = float(out.get("profit_loss") or out.get("realized_profit") or 0)
            if pnl >= 0:
                wins += 1
    p = wins / max(len(rows), 1)
    confidence = min(0.95, 0.4 + (len(rows) / 80.0))
    return {"success_probability": round(p, 3), "confidence": round(confidence, 3)}


def prediction_summary(user_id: int) -> dict[str, Any]:
    trend = forecast_profit_trend(int(user_id))
    risk = predict_risk_spike(int(user_id))
    shift = detect_market_shift(int(user_id))
    opp = predict_opportunity_success(int(user_id), None)
    rec = "Good opportunity window" if trend.get("trend") == "up" and risk.get("risk_level") != "high" else "High risk ahead"
    fb = adjust_model_weights(int(user_id))
    confidence_weight = float(fb.get("confidence_weight") or 1.0)
    trend["confidence"] = round(min(0.99, max(0.05, float(trend.get("confidence") or 0.5) * confidence_weight)), 3)
    opp["confidence"] = round(min(0.99, max(0.05, float(opp.get("confidence") or 0.5) * confidence_weight)), 3)
    return {
        "ok": True,
        "confidence_score": round(
            (float(trend.get("confidence") or 0.5) + float(risk.get("probability") or 0.5) + float(opp.get("confidence") or 0.5))
            / 3.0,
            3,
        ),
        "predicted_risk": risk,
        "profit_trend": trend,
        "market_shift": shift,
        "opportunity_success": opp,
        "feedback_correction": fb,
        "recommended_action": rec,
    }


def prediction_risk_alerts(user_id: int) -> dict[str, Any]:
    s = prediction_summary(int(user_id))
    alerts: list[dict[str, Any]] = []
    risk = s.get("predicted_risk") or {}
    trend = s.get("profit_trend") or {}
    if str(risk.get("risk_level") or "") == "high":
        alerts.append({"level": "high", "message": "High risk ahead", "action": "Tighten limits and lower exposure"})
    if str(trend.get("trend") or "") == "up" and str(risk.get("risk_level") or "") != "high":
        alerts.append({"level": "info", "message": "Good opportunity window", "action": "Allocate capital across top opportunities"})
    if not alerts:
        alerts.append({"level": "medium", "message": "Market neutral", "action": "Keep standard risk controls"})
    return {"ok": True, "alerts": alerts, "summary": s}


def compute_forecasts(organization_id: int) -> dict[str, Any]:
    """
    Lightweight organization forecast API used by reliability tests.
    """
    factory = get_session_factory()
    if not str(os.getenv("DATABASE_URL") or "").strip() and get_session_factory is _ORIGINAL_GET_SESSION_FACTORY:
        raise RuntimeError("DATABASE_URL is required for compute_forecasts")
    if factory is None:
        return {
            "ok": False,
            "organization_id": int(organization_id),
            "data_quality": {"distinct_invoice_months": 0},
            "revenue_inr": _forecast_numeric([]),
        }
    with factory() as session:
        stmt = select(Opportunity.expected_profit)
        org_col = getattr(Opportunity, "organization_id", None)
        if org_col is not None:
            stmt = stmt.where(org_col == int(organization_id))
        rows = session.execute(stmt).all()
    values: list[float] = []
    for row in rows:
        try:
            if isinstance(row, tuple):
                values.append(float(row[0] or 0.0))
            else:
                values.append(float(getattr(row, "expected_profit", 0.0) or 0.0))
        except Exception:
            continue
    forecast = _forecast_numeric(values)
    return {
        "ok": True,
        "organization_id": int(organization_id),
        "data_quality": {"distinct_invoice_months": 0 if not values else 1},
        "revenue_inr": forecast,
    }
