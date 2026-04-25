"""World model engine for market/business/risk context synthesis."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import LearningLog
from services.feedback_engine import calculate_prediction_accuracy
from services.predictive_engine import prediction_summary

_SOURCE_TYPE = "world_model_state"
_SOURCE_ID = 1


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_world_model(user_id: int) -> dict[str, Any]:
    pred = prediction_summary(int(user_id))
    fb = calculate_prediction_accuracy(int(user_id), limit=220)
    trend = str(((pred.get("profit_trend") or {}).get("trend")) or "neutral")
    risk = str(((pred.get("predicted_risk") or {}).get("risk_level")) or "medium")
    win_conf = float(pred.get("confidence_score") or 0.5)
    trust = float(fb.get("system_trust_score") or 50.0)
    market_regime = "expansion" if trend == "up" and risk != "high" else ("defensive" if risk == "high" else "balanced")
    business_dynamics = {
        "profit_trend": trend,
        "execution_quality": "strong" if trust >= 70 else ("recovering" if trust >= 50 else "fragile"),
        "confidence": round(win_conf, 3),
    }
    risk_patterns = {
        "level": risk,
        "drift": str(fb.get("trend") or "stable"),
        "error_pct": float(fb.get("prediction_error_pct") or 0),
    }
    return {
        "ok": True,
        "market_behavior": {"regime": market_regime, "signal_confidence": round(win_conf, 3)},
        "business_dynamics": business_dynamics,
        "risk_patterns": risk_patterns,
        "updated_at": _now_iso(),
    }


def persist_world_model(user_id: int, organization_id: int) -> dict[str, Any]:
    model = build_world_model(int(user_id))
    factory = _session_factory_or_none()
    if factory is None:
        return model
    with factory() as session:
        row = LearningLog(
            resolved_by_user_id=int(user_id),
            organization_id=int(organization_id),
            source_type=_SOURCE_TYPE,
            source_id=_SOURCE_ID,
            input_data_json={"at": _now_iso()},
            outcome_json=model,
            success=True,
            outcome="success",
            action_type="world_model_update",
            lesson_summary="World model updated from prediction and outcomes.",
            context={"engine": "world_model"},
            result=model,
        )
        session.add(row)
        session.commit()
    return model


def get_world_model(user_id: int) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        return build_world_model(int(user_id))
    with factory() as session:
        row = (
            session.execute(
                select(LearningLog)
                .where(
                    LearningLog.resolved_by_user_id == int(user_id),
                    LearningLog.source_type == _SOURCE_TYPE,
                    LearningLog.source_id == _SOURCE_ID,
                )
                .order_by(LearningLog.created_at.desc(), LearningLog.id.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
    if row is None:
        return build_world_model(int(user_id))
    out = row.outcome_json or {}
    out["ok"] = True
    return out
