"""
Self-Evolution Phase 1: nightly learning pipeline.

This module is the pattern-extraction half of the loop. The model-training half
lives in :mod:`services.ml.outcome_predictor`. Together with :mod:`services.ml.model_registry`
they implement: read past outcomes → extract patterns → update confidences →
retrain predictor → produce a weekly "what I learned" digest.

Public entry points
-------------------
- ``run_nightly(organization_id=None)`` — full nightly job (idempotent)
- ``extract_patterns(organization_id=None)`` — pattern extraction only
- ``update_pattern_confidences(...)``       — DB upsert of patterns
- ``retrain_predictor(...)``                — wraps ``outcome_predictor.train``
- ``record_outcome_feedback(...)``          — write predicted vs actual feedback
- ``weekly_report(organization_id=None, days=7)`` — "what I learned" payload
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import LearningLog, LearningPattern, OutcomeFeedback
from services.ml import outcome_predictor
from services.ml.model_registry import ModelRegistry

_LOG = logging.getLogger(__name__)

PATTERN_COMMAND_SUCCESS = "command_success"
PATTERN_PREDICTION_ACCURACY = "prediction_accuracy"
PATTERN_BUSINESS_ACTION_OUTCOME = "business_action_outcome"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _factory_or_none():
    try:
        return get_session_factory()
    except Exception as exc:
        _LOG.debug("learning_pipeline session factory unavailable: %s", exc)
        return None


def _is_success(row: LearningLog) -> bool:
    if row.success is True:
        return True
    if row.success is False:
        return False
    return str(row.outcome or "").strip().lower() in ("success", "ok", "approved", "applied")


def _action_kind(row: LearningLog) -> str:
    """Bucket an action_type into one of three pattern lanes."""
    s = str(row.action_type or "").strip().lower()
    if not s:
        return PATTERN_COMMAND_SUCCESS
    if "predict" in s or "forecast" in s or "world_model" in s:
        return PATTERN_PREDICTION_ACCURACY
    if any(kw in s for kw in ("inventory", "billing", "invoice", "sale", "production", "purchase", "stock", "trade")):
        return PATTERN_BUSINESS_ACTION_OUTCOME
    return PATTERN_COMMAND_SUCCESS


# ---------------------------------------------------------------------------
# Extract patterns
# ---------------------------------------------------------------------------


def extract_patterns(
    organization_id: int | None = None, *, lookback_days: int = 30
) -> dict[str, dict[str, dict[str, Any]]]:
    """Compute rolling success-rate patterns from ``LearningLog``.

    Returns ``{pattern_type: {pattern_key: {...}}}``. Empty dict when DB is unreachable.
    """
    factory = _factory_or_none()
    if factory is None:
        return {}
    since = _now() - timedelta(days=max(1, int(lookback_days)))
    with factory() as session:
        stmt = (
            select(LearningLog)
            .where(LearningLog.created_at >= since)
            .order_by(LearningLog.created_at.desc())
            .limit(20_000)
        )
        if organization_id is not None:
            stmt = stmt.where(LearningLog.organization_id == int(organization_id))
        rows: list[LearningLog] = list(session.execute(stmt).scalars().all())

    buckets: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"total": 0, "success": 0})
    )
    samples: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))

    for row in rows:
        kind = _action_kind(row)
        key = (row.action_type or "unknown").strip().lower()[:255] or "unknown"
        b = buckets[kind][key]
        b["total"] += 1
        if _is_success(row):
            b["success"] += 1
        if len(samples[kind][key]) < 3 and (row.lesson_summary or ""):
            samples[kind][key].append(str(row.lesson_summary)[:240])

    out: dict[str, dict[str, dict[str, Any]]] = {}
    for kind, by_key in buckets.items():
        out[kind] = {}
        for key, b in by_key.items():
            total = max(int(b["total"] or 0), 0)
            succ = max(int(b["success"] or 0), 0)
            confidence = (succ / total) if total > 0 else 0.0
            out[kind][key] = {
                "confidence": round(confidence, 4),
                "evidence_count": total,
                "success_count": succ,
                "samples": list(samples[kind][key]),
            }
    return out


# ---------------------------------------------------------------------------
# Persist patterns (upsert by (organization_id, pattern_type, pattern_key))
# ---------------------------------------------------------------------------


def update_pattern_confidences(
    patterns: dict[str, dict[str, dict[str, Any]]],
    *,
    organization_id: int | None = None,
) -> dict[str, int]:
    """Upsert pattern rows. Returns ``{"upserted": N, "kinds": K}``."""
    factory = _factory_or_none()
    if factory is None:
        return {"upserted": 0, "kinds": 0}
    upserted = 0
    kinds = 0
    now = _now()
    with factory() as session:
        for pattern_type, by_key in patterns.items():
            kinds += 1
            for pattern_key, info in by_key.items():
                key_str = (pattern_key or "")[:255]
                org_filter = (
                    LearningPattern.organization_id == int(organization_id)
                    if organization_id is not None
                    else LearningPattern.organization_id.is_(None)
                )
                existing = (
                    session.execute(
                        select(LearningPattern).where(
                            org_filter,
                            LearningPattern.pattern_type == str(pattern_type),
                            LearningPattern.pattern_key == key_str,
                        )
                    )
                    .scalars()
                    .first()
                )
                if existing is None:
                    row = LearningPattern(
                        organization_id=int(organization_id) if organization_id is not None else None,
                        pattern_type=str(pattern_type),
                        pattern_key=key_str,
                        confidence=float(info.get("confidence") or 0.0),
                        evidence_count=int(info.get("evidence_count") or 0),
                        sample_payload={
                            "samples": list(info.get("samples") or []),
                            "success_count": int(info.get("success_count") or 0),
                        },
                        last_updated=now,
                    )
                    session.add(row)
                else:
                    existing.confidence = float(info.get("confidence") or 0.0)
                    existing.evidence_count = int(info.get("evidence_count") or 0)
                    existing.sample_payload = {
                        "samples": list(info.get("samples") or []),
                        "success_count": int(info.get("success_count") or 0),
                    }
                    existing.last_updated = now
                upserted += 1
        session.commit()
    return {"upserted": upserted, "kinds": kinds}


# ---------------------------------------------------------------------------
# Outcome feedback writer
# ---------------------------------------------------------------------------


def record_outcome_feedback(
    *,
    model_name: str,
    action_id: str,
    action_type: str,
    predicted_outcome: dict[str, Any],
    actual_outcome: dict[str, Any],
    organization_id: int | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Persist a single predicted-vs-actual pair, computing a 0..1 accuracy_score.

    Heuristic for ``accuracy_score``:
    - If predicted has ``probability`` (0..1) and actual has ``success`` (bool/int):
      score = 1 - |probability - 1{success}|
    - Else if both share boolean ``success``: score = 1 if equal else 0
    - Else 0.5 (no comparable signal).
    """
    factory = _factory_or_none()
    if factory is None:
        return {"ok": False, "error": "no_db"}
    score = _compute_accuracy_score(predicted_outcome or {}, actual_outcome or {})
    with factory() as session:
        row = OutcomeFeedback(
            organization_id=int(organization_id) if organization_id is not None else None,
            user_id=int(user_id) if user_id is not None else None,
            model_name=str(model_name)[:128],
            action_id=str(action_id)[:128],
            action_type=str(action_type)[:128],
            predicted_outcome=dict(predicted_outcome or {}),
            actual_outcome=dict(actual_outcome or {}),
            accuracy_score=float(score),
        )
        session.add(row)
        session.commit()
        rid = int(row.id)
    return {"ok": True, "id": rid, "accuracy_score": round(score, 4)}


def _compute_accuracy_score(predicted: dict[str, Any], actual: dict[str, Any]) -> float:
    try:
        if "probability" in predicted and ("success" in actual or "actual" in actual):
            prob = max(0.0, min(float(predicted.get("probability") or 0.0), 1.0))
            actual_truth = actual.get("success") if "success" in actual else actual.get("actual")
            target = 1.0 if bool(actual_truth) else 0.0
            return max(0.0, 1.0 - abs(prob - target))
        if "success" in predicted and "success" in actual:
            return 1.0 if bool(predicted.get("success")) == bool(actual.get("success")) else 0.0
    except Exception:
        return 0.5
    return 0.5


# ---------------------------------------------------------------------------
# Retrain predictor
# ---------------------------------------------------------------------------


def retrain_predictor(
    *,
    organization_id: int | None = None,
    algorithm: str = "random_forest",
) -> dict[str, Any]:
    """Trigger a retrain of the active outcome predictor."""
    return outcome_predictor.train(
        organization_id=organization_id, algorithm=algorithm, activate=True
    )


# ---------------------------------------------------------------------------
# Weekly "what I learned" report
# ---------------------------------------------------------------------------


def weekly_report(
    organization_id: int | None = None, *, days: int = 7
) -> dict[str, Any]:
    """Compose a JSON-safe weekly digest."""
    factory = _factory_or_none()
    since = _now() - timedelta(days=max(1, int(days)))

    rows: list[LearningLog] = []
    if factory is not None:
        with factory() as session:
            stmt = (
                select(LearningLog)
                .where(LearningLog.created_at >= since)
                .order_by(LearningLog.created_at.desc())
                .limit(5_000)
            )
            if organization_id is not None:
                stmt = stmt.where(LearningLog.organization_id == int(organization_id))
            rows = list(session.execute(stmt).scalars().all())

    total = len(rows)
    successes = sum(1 for r in rows if _is_success(r))
    failures = total - successes
    success_rate = (successes / total) if total > 0 else 0.0
    by_type = Counter(((r.action_type or "unknown").lower() for r in rows))
    top_types = by_type.most_common(5)

    failed_summaries = [
        (r.lesson_summary or "")[:200] for r in rows if not _is_success(r) and (r.lesson_summary or "")
    ][:5]
    success_summaries = [
        (r.lesson_summary or "")[:200] for r in rows if _is_success(r) and (r.lesson_summary or "")
    ][:5]

    predictor_acc = outcome_predictor.get_recent_accuracy(days=days)
    active = ModelRegistry.get_active(outcome_predictor.MODEL_NAME)
    latest = ModelRegistry.get_latest(outcome_predictor.MODEL_NAME)

    return {
        "ok": True,
        "window": {"days": int(days), "since": since.isoformat(), "to": _now().isoformat()},
        "totals": {
            "actions": total,
            "successes": successes,
            "failures": failures,
            "success_rate": round(success_rate, 4),
        },
        "top_action_types": [{"action_type": k, "count": int(v)} for k, v in top_types],
        "lessons": {
            "from_failures": failed_summaries,
            "from_successes": success_summaries,
        },
        "predictor": {
            "accuracy_recent": predictor_acc,
            "active": active.to_dict() if active else None,
            "latest": latest.to_dict() if latest else None,
        },
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_nightly(organization_id: int | None = None) -> dict[str, Any]:
    """Run the full nightly cycle. Idempotent."""
    started = _now()
    patterns = extract_patterns(organization_id=organization_id, lookback_days=30)
    upsert = update_pattern_confidences(patterns, organization_id=organization_id)
    train_result = retrain_predictor(organization_id=organization_id)
    report = weekly_report(organization_id=organization_id, days=7)
    elapsed_ms = int((_now() - started).total_seconds() * 1000)
    out = {
        "ok": True,
        "started_at": started.isoformat(),
        "elapsed_ms": elapsed_ms,
        "patterns_upserted": int(upsert.get("upserted") or 0),
        "pattern_kinds": int(upsert.get("kinds") or 0),
        "train_result": train_result,
        "weekly_report": report,
    }
    _LOG.info(
        "learning_pipeline.run_nightly: patterns=%s train_ok=%s elapsed_ms=%s",
        out["patterns_upserted"],
        bool(train_result.get("ok")),
        elapsed_ms,
    )
    return out


__all__: Iterable[str] = (
    "PATTERN_COMMAND_SUCCESS",
    "PATTERN_PREDICTION_ACCURACY",
    "PATTERN_BUSINESS_ACTION_OUTCOME",
    "extract_patterns",
    "update_pattern_confidences",
    "record_outcome_feedback",
    "retrain_predictor",
    "weekly_report",
    "run_nightly",
)
