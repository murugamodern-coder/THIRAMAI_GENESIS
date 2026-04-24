"""Ground-truth feedback validation and drift correction engine."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import LearningLog


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _signed_error(predicted: dict[str, Any], actual: dict[str, Any]) -> float:
    p = _safe_float(predicted.get("profit"), 0.0)
    a = _safe_float(actual.get("profit"), 0.0)
    if abs(p) < 1e-9:
        return 0.0 if abs(a) < 1e-9 else (-1.0 if a > 0 else 1.0)
    return (p - a) / max(abs(p), 1.0)


def record_prediction_vs_actual(
    execution_id: str,
    predicted: dict[str, Any],
    actual: dict[str, Any],
    *,
    user_id: int,
    organization_id: int,
) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        return {"ok": False, "error": "Database unavailable"}
    err = _signed_error(predicted or {}, actual or {})
    abs_err = abs(err)
    confidence = _safe_float((predicted or {}).get("confidence"), 0.5)
    predicted_success = bool((predicted or {}).get("success", _safe_float((predicted or {}).get("profit"), 0) >= 0))
    actual_success = bool((actual or {}).get("success", _safe_float((actual or {}).get("profit"), 0) >= 0))
    calibration_gap = abs((1.0 if actual_success else 0.0) - confidence)
    strategy = str((predicted or {}).get("strategy") or (predicted or {}).get("source_type") or "general")
    with factory() as session:
        row = LearningLog(
            user_id=int(user_id),
            organization_id=int(organization_id),
            source_type="feedback",
            source_id=None,
            input_data_json={
                "execution_id": str(execution_id or ""),
                "predicted": predicted or {},
                "strategy": strategy,
                "error_pct": round(abs_err * 100.0, 3),
                "calibration_gap": round(calibration_gap, 4),
            },
            outcome_json={
                "actual": actual or {},
                "actual_success": actual_success,
                "signed_error": round(err, 5),
            },
            success=bool(abs_err <= 0.25),
            outcome="success" if abs_err <= 0.25 else "failure",
            action_type="feedback_validation",
            lesson_summary="Prediction validated against actual execution outcome.",
            context={"execution_id": str(execution_id or ""), "strategy": strategy},
            result={"error_pct": round(abs_err * 100.0, 3), "calibration_gap": round(calibration_gap, 4)},
        )
        session.add(row)
        session.commit()
        return {"ok": True, "id": int(row.id), "error_pct": round(abs_err * 100.0, 3), "calibration_gap": round(calibration_gap, 4)}


def _fetch_feedback_rows(user_id: int, limit: int = 300) -> list[LearningLog]:
    factory = _session_factory_or_none()
    if factory is None:
        return []
    with factory() as session:
        return (
            session.execute(
                select(LearningLog)
                .where(LearningLog.user_id == int(user_id), LearningLog.source_type == "feedback")
                .order_by(LearningLog.created_at.desc(), LearningLog.id.desc())
                .limit(max(1, min(int(limit), 1000)))
            )
            .scalars()
            .all()
        )


def calculate_prediction_accuracy(user_id: int, limit: int = 300) -> dict[str, Any]:
    rows = _fetch_feedback_rows(int(user_id), limit=limit)
    if not rows:
        return {
            "ok": True,
            "sample_size": 0,
            "accuracy_pct": 0.0,
            "prediction_error_pct": 0.0,
            "confidence_calibration": 0.0,
            "per_strategy_accuracy": [],
            "trend": "stable",
            "system_trust_score": 50.0,
        }
    total = len(rows)
    acc_hits = 0
    error_sum = 0.0
    calib_sum = 0.0
    by_strategy: dict[str, dict[str, float]] = {}
    recent_err = []
    prior_err = []
    for idx, row in enumerate(rows):
        inp = row.input_data_json or {}
        err_pct = _safe_float(inp.get("error_pct"), 0.0)
        gap = _safe_float(inp.get("calibration_gap"), 0.0)
        strategy = str(inp.get("strategy") or "general")
        error_sum += err_pct
        calib_sum += gap
        if err_pct <= 25.0:
            acc_hits += 1
        if idx < 50:
            recent_err.append(err_pct)
        elif idx < 100:
            prior_err.append(err_pct)
        bucket = by_strategy.setdefault(strategy, {"n": 0.0, "hits": 0.0, "err": 0.0})
        bucket["n"] += 1
        bucket["hits"] += 1 if err_pct <= 25.0 else 0
        bucket["err"] += err_pct
    accuracy = (acc_hits / max(total, 1)) * 100.0
    avg_err = error_sum / max(total, 1)
    calibration = 1.0 - min(1.0, (calib_sum / max(total, 1)))
    per_strategy = []
    for name, val in by_strategy.items():
        n = max(val["n"], 1.0)
        per_strategy.append(
            {
                "strategy": name,
                "accuracy_pct": round((val["hits"] / n) * 100.0, 2),
                "avg_error_pct": round(val["err"] / n, 2),
                "sample_size": int(n),
            }
        )
    per_strategy.sort(key=lambda x: x["accuracy_pct"], reverse=True)
    r = sum(recent_err) / max(len(recent_err), 1)
    p = sum(prior_err) / max(len(prior_err), 1) if prior_err else r
    trend = "improving" if r < p * 0.95 else ("degrading" if r > p * 1.05 else "stable")
    trust = max(0.0, min(100.0, (accuracy * 0.6) + ((100.0 - avg_err) * 0.25) + (calibration * 100.0 * 0.15)))
    return {
        "ok": True,
        "sample_size": total,
        "accuracy_pct": round(accuracy, 2),
        "prediction_error_pct": round(avg_err, 2),
        "confidence_calibration": round(calibration, 3),
        "per_strategy_accuracy": per_strategy[:8],
        "trend": trend,
        "system_trust_score": round(trust, 2),
    }


def adjust_model_weights(user_id: int) -> dict[str, Any]:
    rows = _fetch_feedback_rows(int(user_id), limit=120)
    if not rows:
        return {
            "ok": True,
            "confidence_weight": 1.0,
            "allocation_bias": 1.0,
            "mode": "neutral",
            "reason": "No feedback history yet",
        }
    signed_errors = []
    for row in rows[:60]:
        out = row.outcome_json or {}
        signed_errors.append(_safe_float(out.get("signed_error"), 0.0))
    if not signed_errors:
        return {
            "ok": True,
            "confidence_weight": 1.0,
            "allocation_bias": 1.0,
            "mode": "neutral",
            "reason": "No signed error records",
        }
    over_ratio = sum(1 for e in signed_errors if e > 0.12) / len(signed_errors)
    under_ratio = sum(1 for e in signed_errors if e < -0.12) / len(signed_errors)
    if over_ratio >= 0.45:
        return {
            "ok": True,
            "confidence_weight": 0.82,
            "allocation_bias": 0.93,
            "mode": "defensive",
            "reason": "Repeated overestimation detected; confidence weight reduced.",
        }
    if under_ratio >= 0.45:
        return {
            "ok": True,
            "confidence_weight": 1.08,
            "allocation_bias": 1.1,
            "mode": "offensive",
            "reason": "Repeated underestimation detected; allocation bias increased.",
        }
    return {
        "ok": True,
        "confidence_weight": 1.0,
        "allocation_bias": 1.0,
        "mode": "neutral",
        "reason": "Model is reasonably calibrated.",
    }


def feedback_drift(user_id: int) -> dict[str, Any]:
    metrics = calculate_prediction_accuracy(int(user_id), limit=220)
    weights = adjust_model_weights(int(user_id))
    return {
        "ok": True,
        "trend": metrics.get("trend", "stable"),
        "prediction_error_pct": metrics.get("prediction_error_pct", 0.0),
        "confidence_calibration": metrics.get("confidence_calibration", 0.0),
        "recommended_adjustment": weights,
        "updated_at": _now().isoformat(),
    }
