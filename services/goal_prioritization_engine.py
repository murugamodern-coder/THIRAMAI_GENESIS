"""Dynamic goal prioritization engine for autonomous execution."""

from __future__ import annotations

from datetime import date
from typing import Any

from services.feedback_engine import adjust_model_weights
from services.goal_engine import goal_progress_snapshot
from services.predictive_engine import prediction_summary


def _risk_rank(level: str) -> float:
    lv = str(level or "medium").lower()
    if lv == "low":
        return 0.2
    if lv == "high":
        return 1.0
    return 0.55


def _urgency_score(description: str) -> float:
    d = str(description or "").lower()
    if "today" in d or "urgent" in d or "immediate" in d:
        return 0.95
    if "week" in d:
        return 0.75
    return 0.55


def _profit_potential(description: str, trend: str) -> float:
    d = str(description or "").lower()
    base = 0.6 if str(trend or "neutral") == "up" else 0.45
    if "revenue" in d or "profit" in d or "opportunit" in d or "scale" in d:
        base += 0.2
    return max(0.1, min(1.0, base))


def prioritize_goals(user_id: int) -> dict[str, Any]:
    snap = goal_progress_snapshot(int(user_id), "week")
    items = list(snap.get("items") or [])
    pred = prediction_summary(int(user_id))
    trend = str(((pred.get("profit_trend") or {}).get("trend")) or "neutral")
    risk_level = str(((pred.get("predicted_risk") or {}).get("risk_level")) or "medium")
    risk_score = _risk_rank(risk_level)
    correction = adjust_model_weights(int(user_id))
    conf_weight = float(correction.get("confidence_weight") or 1.0)
    ranked: list[dict[str, Any]] = []
    for g in items:
        desc = str(g.get("description") or "")
        progress = float(g.get("progress_pct") or 0.0)
        confidence = min(1.0, max(0.1, float(pred.get("confidence_score") or 0.5) * conf_weight))
        profit = _profit_potential(desc, trend)
        urgency = _urgency_score(desc)
        # Less-progressed but active goals get more execution priority.
        progress_boost = max(0.1, min(1.0, (100.0 - progress) / 100.0))
        total = (profit * 0.32) + (urgency * 0.24) + ((1.0 - risk_score) * 0.2) + (confidence * 0.14) + (progress_boost * 0.1)
        ranked.append(
            {
                **g,
                "priority_score": round(total, 4),
                "signals": {
                    "profit_potential": round(profit, 3),
                    "urgency": round(urgency, 3),
                    "risk": round(risk_score, 3),
                    "confidence": round(confidence, 3),
                },
            }
        )
    ranked.sort(key=lambda x: float(x.get("priority_score") or 0), reverse=True)
    return {
        "ok": True,
        "risk_level": risk_level,
        "confidence_weight": conf_weight,
        "items": ranked,
        "top_goal": ranked[0] if ranked else None,
    }
