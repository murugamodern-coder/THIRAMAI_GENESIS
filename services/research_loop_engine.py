"""Hypothesis -> experiment -> compare -> promote research loop engine."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import LearningLog
from services.learning_engine import update_strategy_profiles
from services.predictive_engine import prediction_summary


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def generate_hypotheses(user_id: int, domain: str) -> dict[str, Any]:
    pred = prediction_summary(int(user_id))
    trend = str(((pred.get("profit_trend") or {}).get("trend")) or "neutral")
    risk = str(((pred.get("predicted_risk") or {}).get("risk_level")) or "medium")
    hypotheses = [
        {
            "title": f"{domain} allocation sensitivity test",
            "hypothesis": "Risk-adjusted allocation improves realized return consistency.",
        },
        {
            "title": f"{domain} timing hypothesis",
            "hypothesis": f"When trend is {trend} and risk is {risk}, selective execution outperforms baseline.",
        },
    ]
    return {"ok": True, "domain": str(domain or "general"), "items": hypotheses}


def run_experiment(user_id: int, organization_id: int, hypothesis_id: str, variant_config: dict[str, Any]) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        return {"ok": False, "error": "Database unavailable"}
    variant = variant_config or {}
    baseline = float(variant.get("baseline_score") or 0.5)
    candidate = float(variant.get("candidate_score") or 0.55)
    delta = candidate - baseline
    success = delta >= 0
    with factory() as session:
        row = LearningLog(
            user_id=int(user_id),
            organization_id=int(organization_id),
            source_type="research_experiment",
            source_id=None,
            input_data_json={"hypothesis_id": str(hypothesis_id or ""), "variant": variant},
            outcome_json={"baseline": baseline, "candidate": candidate, "delta": delta},
            success=bool(success),
            outcome="success" if success else "failure",
            action_type="research_experiment_run",
            lesson_summary="Research loop experiment executed.",
            context={"domain": variant.get("domain") or "general"},
            result={"delta": delta},
        )
        session.add(row)
        session.commit()
        rid = int(row.id)
    return {"ok": True, "experiment_id": rid, "delta": round(delta, 4), "winner": "candidate" if success else "baseline"}


def compare_experiment_results(user_id: int, experiment_group_id: str) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        return {"ok": False, "error": "Database unavailable"}
    with factory() as session:
        rows = (
            session.execute(
                select(LearningLog)
                .where(LearningLog.user_id == int(user_id), LearningLog.source_type == "research_experiment")
                .order_by(LearningLog.created_at.desc(), LearningLog.id.desc())
                .limit(40)
            )
            .scalars()
            .all()
        )
    wins = 0
    deltas: list[float] = []
    for r in rows:
        out = r.outcome_json or {}
        d = float(out.get("delta") or 0)
        deltas.append(d)
        if d >= 0:
            wins += 1
    avg = sum(deltas) / max(len(deltas), 1) if deltas else 0.0
    return {
        "ok": True,
        "experiment_group_id": str(experiment_group_id or ""),
        "sample_size": len(rows),
        "candidate_win_rate": round((wins / max(len(rows), 1)) * 100.0, 2) if rows else 0.0,
        "avg_delta": round(avg, 4),
        "recommendation": "promote" if avg >= 0 else "hold",
    }


def promote_strategy_update(user_id: int, experiment_group_id: str) -> dict[str, Any]:
    cmp = compare_experiment_results(int(user_id), str(experiment_group_id or ""))
    if not cmp.get("ok"):
        return cmp
    if str(cmp.get("recommendation")) != "promote":
        return {"ok": True, "promoted": False, "reason": "No positive edge vs baseline", "comparison": cmp}
    update = update_strategy_profiles(int(user_id))
    return {"ok": True, "promoted": True, "comparison": cmp, "strategy_update": update}
