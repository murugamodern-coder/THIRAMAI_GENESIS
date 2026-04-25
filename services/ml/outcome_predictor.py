"""
Self-Evolution Phase 1: outcome predictor (success vs failure of an action).

Trains a small scikit-learn classifier from ``LearningLog`` rows and registers each
trained version through ``services.ml.model_registry``. The model file is persisted
via ``joblib`` to ``services.ml.model_registry.model_artifact_path``.

Features (intentionally small to start):
- ``action_type`` (categorical, hashed to bucket id)
- ``hour_of_day``
- ``day_of_week``
- ``inventory_level`` (from ``context.inventory_level`` if present, else 0)
- ``revenue_trend``  (from ``context.revenue_trend`` mapped to {-1, 0, 1})
- ``past_success_rate`` (rolling success rate for that ``action_type``)

Target: ``success`` (1) vs ``failure`` (0) derived from ``LearningLog.success`` /
``LearningLog.outcome``.

If scikit-learn or joblib is not installed, this module degrades gracefully:
training returns ``{"ok": False, "error": "sklearn_missing"}`` and prediction
returns a heuristic baseline equal to the historical success rate of the action
type (50% if unknown).
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import LearningLog
from services.ml.model_registry import ModelRegistry, model_artifact_path, next_version

_LOG = logging.getLogger(__name__)

MODEL_NAME = "outcome_predictor"
_MIN_TRAINING_SAMPLES = int(os.getenv("THIRAMAI_OUTCOME_PREDICTOR_MIN_SAMPLES") or "50")
_TRAINING_LOOKBACK_DAYS = int(os.getenv("THIRAMAI_OUTCOME_PREDICTOR_LOOKBACK_DAYS") or "180")
_ACTION_TYPE_BUCKETS = 64

# ---------------------------------------------------------------------------
# Optional sklearn / joblib imports (graceful)
# ---------------------------------------------------------------------------

try:  # pragma: no cover - import-time check
    import joblib  # type: ignore[import-not-found]
    from sklearn.ensemble import RandomForestClassifier  # type: ignore[import-not-found]
    from sklearn.linear_model import LogisticRegression  # type: ignore[import-not-found]
    from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score  # type: ignore[import-not-found]
    from sklearn.model_selection import train_test_split  # type: ignore[import-not-found]

    _SKLEARN_AVAILABLE = True
except Exception as _exc:  # pragma: no cover
    joblib = None  # type: ignore[assignment]
    RandomForestClassifier = None  # type: ignore[assignment]
    LogisticRegression = None  # type: ignore[assignment]
    accuracy_score = f1_score = precision_score = recall_score = None  # type: ignore[assignment]
    train_test_split = None  # type: ignore[assignment]
    _SKLEARN_AVAILABLE = False
    _LOG.info("scikit-learn unavailable; outcome_predictor in baseline mode (%s)", _exc)


def sklearn_available() -> bool:
    """Public probe for callers that want to display capability."""
    return bool(_SKLEARN_AVAILABLE)


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------


def _bucket_action_type(action_type: str) -> int:
    raw = (action_type or "unknown").strip().lower().encode("utf-8")
    if not raw:
        return 0
    digest = hashlib.blake2s(raw, digest_size=4).digest()
    return int.from_bytes(digest, "big") % _ACTION_TYPE_BUCKETS


def _trend_to_int(value: Any) -> int:
    s = str(value or "").strip().lower()
    if s in ("up", "rising", "improving", "positive", "gain"):
        return 1
    if s in ("down", "falling", "declining", "negative", "loss"):
        return -1
    return 0


def _row_features(
    *,
    action_type: str,
    when: datetime,
    context: dict[str, Any] | None,
    past_success_rate: float,
) -> list[float]:
    ctx = context if isinstance(context, dict) else {}
    try:
        inv = float(ctx.get("inventory_level") or ctx.get("inventory") or 0.0)
    except (TypeError, ValueError):
        inv = 0.0
    inv = max(-1.0, min(inv / 1000.0, 10.0))
    return [
        float(_bucket_action_type(action_type)),
        float(when.hour if when else 0),
        float(when.weekday() if when else 0),
        inv,
        float(_trend_to_int(ctx.get("revenue_trend"))),
        max(0.0, min(1.0, float(past_success_rate or 0.0))),
    ]


def _is_success(row: LearningLog) -> int:
    if row.success is True:
        return 1
    if row.success is False:
        return 0
    s = str(row.outcome or "").strip().lower()
    return 1 if s in ("success", "ok", "approved", "applied") else 0


def _load_training_rows(
    organization_id: int | None, lookback_days: int
) -> list[LearningLog]:
    factory = _factory_or_none()
    if factory is None:
        return []
    since = datetime.now(timezone.utc) - timedelta(days=max(1, int(lookback_days)))
    with factory() as session:
        stmt = (
            select(LearningLog)
            .where(LearningLog.created_at >= since)
            .order_by(LearningLog.created_at.asc(), LearningLog.id.asc())
            .limit(20_000)
        )
        if organization_id is not None:
            stmt = stmt.where(LearningLog.organization_id == int(organization_id))
        rows = list(session.execute(stmt).scalars().all())
    return rows


def _build_dataset(
    rows: list[LearningLog],
) -> tuple[list[list[float]], list[int], dict[str, dict[str, int]]]:
    """Produce ``(X, y, action_type_stats)`` with per-action rolling success rate."""
    type_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "success": 0})
    X: list[list[float]] = []
    y: list[int] = []
    for row in rows:
        atype = str(row.action_type or "unknown")
        stats = type_stats[atype]
        prior_total = int(stats["total"])
        prior_succ = int(stats["success"])
        prior_rate = (prior_succ / prior_total) if prior_total > 0 else 0.5
        feats = _row_features(
            action_type=atype,
            when=row.created_at or datetime.now(timezone.utc),
            context=row.context or row.input_data_json or {},
            past_success_rate=prior_rate,
        )
        target = _is_success(row)
        X.append(feats)
        y.append(target)
        stats["total"] = prior_total + 1
        stats["success"] = prior_succ + target
    return X, y, dict(type_stats)


# ---------------------------------------------------------------------------
# Train
# ---------------------------------------------------------------------------


def train(
    *,
    organization_id: int | None = None,
    lookback_days: int = _TRAINING_LOOKBACK_DAYS,
    algorithm: str = "random_forest",
    activate: bool = True,
) -> dict[str, Any]:
    """Train, persist, and register a new ``outcome_predictor`` version.

    Returns a JSON-safe dict:

    ``{"ok": bool, "version": str|None, "accuracy": float, "training_samples": int,
       "metrics": {...}, "model_path": str|None, "error": str|None}``
    """
    if not _SKLEARN_AVAILABLE:
        return {
            "ok": False,
            "error": "sklearn_missing",
            "version": None,
            "accuracy": 0.0,
            "training_samples": 0,
            "metrics": {},
            "model_path": None,
        }

    rows = _load_training_rows(organization_id=organization_id, lookback_days=lookback_days)
    if len(rows) < _MIN_TRAINING_SAMPLES:
        return {
            "ok": False,
            "error": f"insufficient_samples ({len(rows)} < {_MIN_TRAINING_SAMPLES})",
            "version": None,
            "accuracy": 0.0,
            "training_samples": len(rows),
            "metrics": {},
            "model_path": None,
        }

    X, y, type_stats = _build_dataset(rows)
    if len(set(y)) < 2:
        return {
            "ok": False,
            "error": "single_class_dataset",
            "version": None,
            "accuracy": 0.0,
            "training_samples": len(rows),
            "metrics": {"class_distribution": {"0": y.count(0), "1": y.count(1)}},
            "model_path": None,
        }

    test_size = 0.25 if len(X) >= 200 else 0.2
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=42, stratify=y
    )

    if str(algorithm).lower() == "logistic_regression":
        clf = LogisticRegression(max_iter=2000, n_jobs=None)
    else:
        clf = RandomForestClassifier(
            n_estimators=120, max_depth=8, random_state=42, n_jobs=1, class_weight="balanced"
        )

    clf.fit(X_train, y_train)
    y_pred = clf.predict(X_test)

    metrics = {
        "accuracy": float(accuracy_score(y_test, y_pred)),
        "precision": float(precision_score(y_test, y_pred, zero_division=0)),
        "recall": float(recall_score(y_test, y_pred, zero_division=0)),
        "f1": float(f1_score(y_test, y_pred, zero_division=0)),
        "algorithm": str(algorithm),
        "class_distribution": {"0": int(y.count(0)), "1": int(y.count(1))},
        "lookback_days": int(lookback_days),
    }

    version = next_version(MODEL_NAME)
    artifact_path = model_artifact_path(MODEL_NAME, version)
    payload = {
        "model": clf,
        "feature_names": [
            "action_type_bucket",
            "hour_of_day",
            "day_of_week",
            "inventory_level_norm",
            "revenue_trend_int",
            "past_success_rate",
        ],
        "type_stats": type_stats,
        "version": version,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "algorithm": algorithm,
    }
    try:
        joblib.dump(payload, artifact_path)
    except Exception as exc:
        _LOG.exception("outcome_predictor.persist_failed")
        return {
            "ok": False,
            "error": f"persist_failed: {exc!s}"[:200],
            "version": version,
            "accuracy": metrics["accuracy"],
            "training_samples": len(rows),
            "metrics": metrics,
            "model_path": str(artifact_path),
        }

    rec = ModelRegistry.register(
        name=MODEL_NAME,
        version=version,
        metrics=metrics,
        path=str(artifact_path),
        training_samples=len(rows),
        notes=f"organization_id={organization_id}",
        activate=activate,
    )
    return {
        "ok": True,
        "version": version,
        "accuracy": metrics["accuracy"],
        "training_samples": len(rows),
        "metrics": metrics,
        "model_path": str(artifact_path),
        "registered": rec.to_dict() if rec else None,
        "active": bool(activate),
    }


# ---------------------------------------------------------------------------
# Predict
# ---------------------------------------------------------------------------


def _load_active_payload() -> dict[str, Any] | None:
    if not _SKLEARN_AVAILABLE or joblib is None:
        return None
    rec = ModelRegistry.get_active(MODEL_NAME)
    if rec is None or not rec.model_path:
        return None
    try:
        return joblib.load(rec.model_path)
    except Exception as exc:
        _LOG.warning("outcome_predictor.load_failed: %s", exc)
        return None


def predict_success(
    *,
    action_type: str,
    when: datetime | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Predict the success probability of a candidate action.

    Returns ``{"ok": bool, "probability": float, "method": str, "model_version": str|None}``.

    Falls back to a historical-success-rate baseline (or 0.5) when no model is
    available or sklearn is missing.
    """
    when = when or datetime.now(timezone.utc)
    context = context or {}

    payload = _load_active_payload()
    if payload is None:
        return _baseline_predict(action_type=action_type, context=context, when=when)

    type_stats = payload.get("type_stats") or {}
    stats = type_stats.get(str(action_type), {"total": 0, "success": 0})
    total = int(stats.get("total") or 0)
    success = int(stats.get("success") or 0)
    prior = (success / total) if total > 0 else 0.5
    feats = _row_features(
        action_type=action_type, when=when, context=context, past_success_rate=prior
    )
    model = payload.get("model")
    try:
        proba = model.predict_proba([feats])[0]
        prob_success = float(proba[1]) if len(proba) > 1 else float(proba[0])
        return {
            "ok": True,
            "probability": round(max(0.0, min(prob_success, 1.0)), 4),
            "method": "model",
            "model_version": str(payload.get("version") or ""),
        }
    except Exception as exc:
        _LOG.warning("outcome_predictor.predict_failed: %s", exc)
        return _baseline_predict(action_type=action_type, context=context, when=when)


def _baseline_predict(
    *,
    action_type: str,
    context: dict[str, Any],
    when: datetime,
) -> dict[str, Any]:
    factory = _factory_or_none()
    if factory is None:
        return {"ok": True, "probability": 0.5, "method": "default_unknown", "model_version": None}
    since = datetime.now(timezone.utc) - timedelta(days=60)
    with factory() as session:
        rows = list(
            session.execute(
                select(LearningLog)
                .where(
                    LearningLog.created_at >= since,
                    LearningLog.action_type == str(action_type),
                )
                .order_by(LearningLog.created_at.desc())
                .limit(500)
            )
            .scalars()
            .all()
        )
    if not rows:
        return {"ok": True, "probability": 0.5, "method": "baseline_no_history", "model_version": None}
    total = len(rows)
    success = sum(1 for r in rows if _is_success(r) == 1)
    prob = success / total if total > 0 else 0.5
    return {
        "ok": True,
        "probability": round(max(0.0, min(prob, 1.0)), 4),
        "method": "baseline_action_history",
        "model_version": None,
        "n": total,
    }


# ---------------------------------------------------------------------------
# Accuracy probe (used by self_evolution_trigger)
# ---------------------------------------------------------------------------


def get_recent_accuracy(*, days: int = 7) -> dict[str, Any]:
    """Return rolling accuracy of the active model, computed from ``OutcomeFeedback``.

    If feedback is empty, returns the latest training-time accuracy as a fallback.
    """
    from core.db.models import OutcomeFeedback

    factory = _factory_or_none()
    if factory is None:
        return {"ok": False, "error": "no_db", "accuracy": 0.0, "samples": 0}
    since = datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))
    with factory() as session:
        rows = list(
            session.execute(
                select(OutcomeFeedback)
                .where(
                    OutcomeFeedback.model_name == MODEL_NAME,
                    OutcomeFeedback.learned_at >= since,
                )
                .order_by(OutcomeFeedback.learned_at.desc())
                .limit(5_000)
            )
            .scalars()
            .all()
        )
    if not rows:
        rec = ModelRegistry.get_active(MODEL_NAME) or ModelRegistry.get_latest(MODEL_NAME)
        return {
            "ok": True,
            "accuracy": float(rec.accuracy) if rec else 0.0,
            "samples": int(rec.training_samples) if rec else 0,
            "source": "training_metrics" if rec else "no_data",
        }
    samples = len(rows)
    score = sum(float(r.accuracy_score or 0.0) for r in rows) / max(samples, 1)
    return {"ok": True, "accuracy": round(score, 4), "samples": samples, "source": "feedback"}


def _factory_or_none():
    try:
        return get_session_factory()
    except Exception as exc:
        _LOG.debug("outcome_predictor session factory unavailable: %s", exc)
        return None
