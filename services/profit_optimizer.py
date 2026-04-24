"""Profit optimization and capital allocation engine."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import LearningLog
from services.feedback_engine import adjust_model_weights
from services.predictive_engine import predict_opportunity_success, predict_risk_spike


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def _risk_factor(risk_level: str) -> float:
    r = str(risk_level or "").lower()
    if r == "low":
        return 1.0
    if r == "high":
        return 0.45
    return 0.72


def _past_success_factor(user_id: int, source_id: int | None = None) -> float:
    """Simple ML-lite success factor from recent learning outcomes."""
    if int(user_id) <= 0:
        return 0.5
    factory = _session_factory_or_none()
    if factory is None:
        return 0.5
    with factory() as session:
        q = select(LearningLog).where(LearningLog.user_id == int(user_id), LearningLog.source_type == "opportunity")
        if source_id:
            q = q.where(LearningLog.source_id == int(source_id))
        rows = session.execute(q.order_by(LearningLog.created_at.desc(), LearningLog.id.desc()).limit(40)).scalars().all()
        if not rows:
            return 0.5
        wins = 0.0
        for row in rows:
            if row.success is True:
                wins += 1
            elif row.success is None:
                out = row.outcome_json or {}
                pnl = float(out.get("profit_loss") or out.get("realized_profit") or 0)
                if pnl >= 0:
                    wins += 1
        return max(0.1, min(1.0, wins / len(rows)))


def score_opportunity(opportunity: dict[str, Any], user_id: int) -> float:
    meta = opportunity.get("metadata_json") if isinstance(opportunity.get("metadata_json"), dict) else {}
    exp_profit = float(opportunity.get("expected_profit") or 0.0)
    confidence = float(meta.get("confidence") or 0.5)
    req_capital = float(meta.get("required_capital") or 1.0)
    roi = exp_profit / max(req_capital, 1.0)
    risk_f = _risk_factor(str(opportunity.get("risk_level") or "medium"))
    success_f = _past_success_factor(int(user_id), int(opportunity.get("id") or 0))
    pred_success = predict_opportunity_success(int(user_id), int(opportunity.get("id") or 0))
    pred_risk = predict_risk_spike(int(user_id))
    weights = adjust_model_weights(int(user_id))
    pred_success_p = float(pred_success.get("success_probability") or 0.5)
    pred_risk_lvl = str(pred_risk.get("risk_level") or "medium")
    pred_risk_penalty = 0.85 if pred_risk_lvl == "high" else (0.95 if pred_risk_lvl == "medium" else 1.0)
    confidence_weight = float(weights.get("confidence_weight") or 1.0)
    allocation_bias = float(weights.get("allocation_bias") or 1.0)
    raw = ((roi * 38.0) + (confidence * 20.0 * confidence_weight) + (success_f * 15.0) + (risk_f * 10.0) + (pred_success_p * 17.0)) * pred_risk_penalty
    raw *= allocation_bias
    return round(max(raw, 0.01), 4)


def allocate_capital(
    opportunities: list[dict[str, Any]],
    total_capital: float,
    *,
    user_id: int,
    max_capital_per_opportunity: float | None = None,
    max_high_risk_share: float = 0.35,
) -> list[dict[str, Any]]:
    """
    Risk-adjusted proportional allocator.

    Constraints:
    - no single opportunity can receive 100%
    - max capital per opportunity
    - cap high-risk bucket share
    """
    cap = max(float(total_capital or 0), 0.0)
    if cap <= 0 or not opportunities:
        return []
    max_per_opp = float(max_capital_per_opportunity or cap * 0.6)
    max_per_opp = min(max_per_opp, cap * 0.8)  # diversification: no 100% single allocation

    scored: list[dict[str, Any]] = []
    for opp in opportunities:
        s = score_opportunity(opp, user_id=int(user_id))
        scored.append({**opp, "_optimizer_score": s})
    scored.sort(key=lambda x: float(x.get("_optimizer_score") or 0), reverse=True)

    total_score = sum(float(x.get("_optimizer_score") or 0) for x in scored) or 1.0
    allocations: list[dict[str, Any]] = []
    remaining = cap

    # First pass: proportional with per-opportunity cap.
    for opp in scored:
        share = float(opp.get("_optimizer_score") or 0) / total_score
        amount = min(cap * share, max_per_opp, remaining)
        expected_profit = float(opp.get("expected_profit") or 0)
        req_capital = float((opp.get("metadata_json") or {}).get("required_capital") or 1.0)
        expected_return = amount * (expected_profit / max(req_capital, 1.0))
        allocations.append(
            {
                "opportunity_id": int(opp.get("id") or 0),
                "title": str(opp.get("title") or ""),
                "risk_level": str(opp.get("risk_level") or "medium"),
                "score": float(opp.get("_optimizer_score") or 0),
                "allocated_capital": round(max(amount, 0.0), 2),
                "expected_return": round(max(expected_return, 0.0), 2),
                "expected_profit": expected_profit,
                "confidence": float((opp.get("metadata_json") or {}).get("confidence") or 0.5),
            }
        )
        remaining -= amount
        if remaining <= 0:
            break

    if remaining > 0 and allocations:
        # Distribute leftovers proportionally to non-capped candidates.
        for row in allocations:
            if remaining <= 0:
                break
            room = max_per_opp - float(row["allocated_capital"])
            if room <= 0:
                continue
            add = min(room, remaining)
            row["allocated_capital"] = round(float(row["allocated_capital"]) + add, 2)
            remaining -= add

    # High-risk cap pass.
    total_alloc = sum(float(r["allocated_capital"]) for r in allocations) or 1.0
    high_rows = [r for r in allocations if str(r.get("risk_level") or "").lower() == "high"]
    high_alloc = sum(float(r["allocated_capital"]) for r in high_rows)
    max_high = total_alloc * max(0.0, min(max_high_risk_share, 1.0))
    if high_alloc > max_high and high_rows:
        excess = high_alloc - max_high
        for r in high_rows:
            if excess <= 0:
                break
            reducible = min(float(r["allocated_capital"]) * 0.5, excess)
            r["allocated_capital"] = round(float(r["allocated_capital"]) - reducible, 2)
            excess -= reducible
        # Reallocate reduced amount to low/medium risk rows.
        reclaim = high_alloc - sum(float(r["allocated_capital"]) for r in high_rows)
        safe_rows = [r for r in allocations if str(r.get("risk_level") or "").lower() != "high"]
        if reclaim > 0 and safe_rows:
            chunk = reclaim / len(safe_rows)
            for r in safe_rows:
                r["allocated_capital"] = round(float(r["allocated_capital"]) + chunk, 2)

    return [r for r in allocations if float(r.get("allocated_capital") or 0) > 0]
