"""
Self-Evolution Phase 2: Online learner.

Implements the *predict-now / resolve-later / partial_fit* loop:

    1. ``predict_and_record(...)``  → run a prediction, store features and the
       predicted probability in ``predictions_pending``.
    2. After ``resolve_after`` passes, ``resolve_pending(...)`` fetches the
       actual outcome (caller-provided or derived from ``LearningLog``) and
       updates the model **incrementally** via ``model.partial_fit(X, y)``.
    3. Each resolution writes an ``OutcomeFeedback`` row so the
       ``self_evolution_trigger`` watcher can detect accuracy regressions.

The online model is a separate ``SGDClassifier`` (logistic loss) registered as
``online_outcome_predictor`` so the batch-trained ``outcome_predictor`` and
``outcome_predictor_ensemble`` are not affected. ``MiniBatchKMeans`` is also
exposed via ``online_cluster_features(...)`` for unsupervised drift detection.

If scikit-learn is not installed every public function returns a documented
"baseline" payload and is a no-op for partial fitting — the rest of the system
still functions.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from core.db.models import (
    LearningLog,
    OutcomeFeedback,
    PredictionPending,
)
from services.ml import outcome_predictor
from services.ml.model_registry import ModelRegistry, model_artifact_path, next_version

_LOG = logging.getLogger(__name__)

ONLINE_MODEL_NAME = "online_outcome_predictor"
KMEANS_MODEL_NAME = "online_feature_cluster"

DEFAULT_RESOLVE_HOURS = int(os.getenv("THIRAMAI_ONLINE_RESOLVE_HOURS") or "24")


# ---------------------------------------------------------------------------
# Optional sklearn / joblib imports
# ---------------------------------------------------------------------------

try:  # pragma: no cover
    import joblib  # type: ignore[import-not-found]
    import numpy as np  # type: ignore[import-not-found]
    from sklearn.cluster import MiniBatchKMeans  # type: ignore[import-not-found]
    from sklearn.linear_model import SGDClassifier  # type: ignore[import-not-found]

    _SKLEARN_AVAILABLE = True
except Exception as _exc:  # pragma: no cover
    joblib = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    MiniBatchKMeans = None  # type: ignore[assignment]
    SGDClassifier = None  # type: ignore[assignment]
    _SKLEARN_AVAILABLE = False
    _LOG.info("scikit-learn unavailable; online_learner in baseline mode (%s)", _exc)


def online_available() -> bool:
    """Public probe used by callers that show capability."""
    return bool(_SKLEARN_AVAILABLE)


def _factory_or_none():
    try:
        from core.database import get_session_factory

        return get_session_factory()
    except Exception as exc:
        _LOG.debug("online_learner session factory unavailable: %s", exc)
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Online classifier (SGDClassifier with partial_fit)
# ---------------------------------------------------------------------------


def _new_sgd_classifier():
    if not _SKLEARN_AVAILABLE:
        return None
    return SGDClassifier(
        loss="log_loss",
        learning_rate="optimal",
        alpha=1e-4,
        random_state=42,
    )


def _load_online_model() -> dict[str, Any] | None:
    if not _SKLEARN_AVAILABLE or joblib is None:
        return None
    rec = ModelRegistry.get_active(ONLINE_MODEL_NAME) or ModelRegistry.get_latest(ONLINE_MODEL_NAME)
    if rec is None or not rec.model_path:
        return None
    try:
        return joblib.load(rec.model_path)
    except Exception as exc:
        _LOG.debug("online model load failed: %s", exc)
        return None


def _persist_online_model(payload: dict[str, Any], *, version: str | None = None) -> dict[str, Any]:
    if not _SKLEARN_AVAILABLE or joblib is None:
        return {"ok": False, "error": "sklearn_missing"}
    version = version or next_version(ONLINE_MODEL_NAME)
    artifact = model_artifact_path(ONLINE_MODEL_NAME, version)
    payload = dict(payload)
    payload.update(
        {
            "version": version,
            "trained_at": _now().isoformat(),
        }
    )
    try:
        joblib.dump(payload, artifact)
    except Exception as exc:
        _LOG.warning("online_learner.persist_failed: %s", exc)
        return {"ok": False, "error": f"persist_failed: {exc!s}"[:200]}
    accuracy = float(payload.get("rolling_accuracy") or 0.0)
    rec = ModelRegistry.register(
        name=ONLINE_MODEL_NAME,
        version=version,
        metrics={
            "accuracy": accuracy,
            "samples_seen": int(payload.get("samples_seen") or 0),
            "online": True,
        },
        path=str(artifact),
        training_samples=int(payload.get("samples_seen") or 0),
        notes="online sgd partial_fit",
        activate=True,
    )
    return {
        "ok": True,
        "version": version,
        "model_path": str(artifact),
        "registered": rec.to_dict() if rec else None,
        "accuracy": accuracy,
    }


def _ensure_online_model() -> dict[str, Any]:
    """Load the active online model or seed a fresh one."""
    payload = _load_online_model()
    if payload is not None and "model" in payload:
        return payload
    model = _new_sgd_classifier()
    return {
        "model": model,
        "samples_seen": 0,
        "rolling_correct": 0,
        "rolling_total": 0,
        "rolling_accuracy": 0.0,
        "feature_names": [
            "action_type_bucket",
            "hour_of_day",
            "day_of_week",
            "inventory_level_norm",
            "revenue_trend_int",
            "past_success_rate",
        ],
        "classes_seen": [],
    }


def _features_for(action_type: str, when: datetime, context: dict[str, Any]) -> list[float]:
    return outcome_predictor._row_features(  # noqa: SLF001
        action_type=action_type,
        when=when,
        context=context or {},
        past_success_rate=float((context or {}).get("past_success_rate") or 0.5),
    )


# ---------------------------------------------------------------------------
# Predict and record
# ---------------------------------------------------------------------------


def predict_and_record(
    *,
    action_type: str,
    action_id: str | None = None,
    when: datetime | None = None,
    context: dict[str, Any] | None = None,
    organization_id: int | None = None,
    user_id: int | None = None,
    resolve_hours: int = DEFAULT_RESOLVE_HOURS,
) -> dict[str, Any]:
    """
    Make a prediction with the online model (or baseline) and record it in
    ``predictions_pending`` for later resolution.

    Returns ``{"ok": bool, "probability": float, "prediction_id": int|None,
    "method": str, "model_version": str|None}``.
    """
    when = when or _now()
    context = context or {}
    feats = _features_for(action_type, when, context)

    method = "baseline"
    probability = 0.5
    model_version: str | None = None

    payload = _ensure_online_model()
    model = payload.get("model")
    if _SKLEARN_AVAILABLE and model is not None and payload.get("samples_seen", 0) > 0:
        try:
            proba = model.predict_proba([feats])[0]
            probability = float(proba[1] if len(proba) > 1 else proba[0])
            method = "online_sgd"
            model_version = str(payload.get("version") or "")
        except Exception as exc:
            _LOG.debug("online predict failed, falling back: %s", exc)
            base = outcome_predictor.predict_success(
                action_type=action_type, when=when, context=context
            )
            probability = float(base.get("probability") or 0.5)
            method = f"fallback_{base.get('method', 'baseline')}"
    else:
        base = outcome_predictor.predict_success(
            action_type=action_type, when=when, context=context
        )
        probability = float(base.get("probability") or 0.5)
        method = f"warmup_{base.get('method', 'baseline')}"
        model_version = base.get("model_version")

    factory = _factory_or_none()
    prediction_id: int | None = None
    if factory is not None:
        try:
            with factory() as session:
                row = PredictionPending(
                    organization_id=organization_id,
                    user_id=user_id,
                    model_name=ONLINE_MODEL_NAME,
                    model_version=str(model_version or ""),
                    action_id=str(action_id or "")[:128],
                    action_type=str(action_type or "")[:128],
                    features_json={
                        "values": feats,
                        "context": context,
                        "when_iso": when.isoformat(),
                    },
                    predicted_outcome={
                        "probability": round(max(0.0, min(probability, 1.0)), 4),
                        "method": method,
                    },
                    predicted_at=when,
                    resolve_after=when + timedelta(hours=max(1, int(resolve_hours))),
                    resolved=False,
                    actual_outcome={},
                    accuracy_score=0.0,
                )
                session.add(row)
                session.commit()
                session.refresh(row)
                prediction_id = int(row.id)
        except Exception as exc:
            _LOG.warning("predict_and_record DB write failed: %s", exc)

    return {
        "ok": True,
        "probability": round(max(0.0, min(probability, 1.0)), 4),
        "prediction_id": prediction_id,
        "method": method,
        "model_version": model_version,
    }


# ---------------------------------------------------------------------------
# Resolve pending predictions and partial_fit
# ---------------------------------------------------------------------------


def _label_from_actual(actual: dict[str, Any] | None) -> int | None:
    """Map an actual outcome dict to ``1`` (success) / ``0`` (failure) / ``None``."""
    if not isinstance(actual, dict):
        return None
    if "success" in actual:
        v = actual.get("success")
        if v is True:
            return 1
        if v is False:
            return 0
    s = str(actual.get("outcome") or "").strip().lower()
    if s in ("success", "ok", "approved", "applied"):
        return 1
    if s in ("failure", "rejected", "failed", "error"):
        return 0
    return None


def _resolve_one(
    session: Any,
    row: PredictionPending,
    *,
    actual_outcome: dict[str, Any] | None,
) -> tuple[int, int | None, float]:
    """Apply one resolution to the running online model + write feedback row.

    Returns ``(updated_int, label, accuracy_increment)``: ``updated_int`` is 1
    when partial_fit succeeded, ``label`` is the resolved 0/1 label, and
    ``accuracy_increment`` is 1.0 when the prediction was correct, else 0.0.
    """
    label = _label_from_actual(actual_outcome)
    if label is None:
        return 0, None, 0.0

    feats_payload = row.features_json or {}
    feats = list(feats_payload.get("values") or [])
    if not feats:
        return 0, label, 0.0

    pred_payload = row.predicted_outcome or {}
    prob = float(pred_payload.get("probability") or 0.5)
    pred_label = 1 if prob >= 0.5 else 0
    correct = 1.0 if pred_label == label else 0.0

    accuracy_score = correct
    feedback = OutcomeFeedback(
        organization_id=row.organization_id,
        user_id=row.user_id,
        model_name=row.model_name or ONLINE_MODEL_NAME,
        action_id=row.action_id or "",
        action_type=row.action_type or "",
        predicted_outcome=dict(pred_payload),
        actual_outcome=dict(actual_outcome or {}),
        accuracy_score=accuracy_score,
    )
    session.add(feedback)

    row.resolved = True
    row.resolved_at = _now()
    row.actual_outcome = dict(actual_outcome or {})
    row.accuracy_score = accuracy_score

    return 1 if _SKLEARN_AVAILABLE else 0, label, correct


def resolve_pending(
    *,
    actual_provider: Any | None = None,
    limit: int = 200,
    organization_id: int | None = None,
) -> dict[str, Any]:
    """
    Resolve up to ``limit`` ready predictions and apply ``partial_fit``.

    ``actual_provider`` is an optional callable
    ``(PredictionPending) -> dict | None`` that returns the actual outcome
    payload. When ``None``, the resolver looks up ``LearningLog`` rows that
    share the same ``action_id`` (or ``action_type`` + ``user_id`` window).
    """
    factory = _factory_or_none()
    if factory is None:
        return {"ok": False, "error": "no_db", "resolved": 0, "updated": 0}

    payload = _ensure_online_model()
    model = payload.get("model")

    resolved_count = 0
    correct_count = 0
    updated_partial_fit = 0

    feature_batch: list[list[float]] = []
    label_batch: list[int] = []

    with factory() as session:
        stmt = (
            select(PredictionPending)
            .where(PredictionPending.resolved.is_(False))
            .where(PredictionPending.resolve_after <= _now())
            .order_by(PredictionPending.resolve_after.asc())
            .limit(int(limit))
        )
        if organization_id is not None:
            stmt = stmt.where(PredictionPending.organization_id == int(organization_id))
        pending = list(session.execute(stmt).scalars().all())

        for row in pending:
            actual = None
            if actual_provider is not None:
                try:
                    actual = actual_provider(row)
                except Exception as exc:
                    _LOG.debug("actual_provider failed: %s", exc)
                    actual = None
            if actual is None:
                actual = _lookup_actual_from_learning_log(session, row)
            if actual is None:
                continue
            partial_ok, label, correct = _resolve_one(
                session, row, actual_outcome=actual
            )
            if label is None:
                continue
            resolved_count += 1
            correct_count += int(correct)
            if partial_ok and _SKLEARN_AVAILABLE and model is not None:
                feats = list((row.features_json or {}).get("values") or [])
                if feats:
                    feature_batch.append(feats)
                    label_batch.append(int(label))

        if feature_batch and _SKLEARN_AVAILABLE and model is not None:
            try:
                X = np.asarray(feature_batch, dtype=float)
                y = np.asarray(label_batch, dtype=int)
                classes = sorted(set(payload.get("classes_seen") or []) | set(label_batch) | {0, 1})
                model.partial_fit(X, y, classes=np.asarray(sorted({0, 1, *classes}), dtype=int))
                payload["model"] = model
                payload["classes_seen"] = sorted(set(int(c) for c in classes))
                payload["samples_seen"] = int(payload.get("samples_seen") or 0) + len(feature_batch)
                payload["rolling_correct"] = int(payload.get("rolling_correct") or 0) + correct_count
                payload["rolling_total"] = int(payload.get("rolling_total") or 0) + resolved_count
                if payload["rolling_total"] > 0:
                    payload["rolling_accuracy"] = round(
                        payload["rolling_correct"] / payload["rolling_total"], 4
                    )
                updated_partial_fit = len(feature_batch)
            except Exception as exc:
                _LOG.warning("online partial_fit failed: %s", exc)

        try:
            session.commit()
        except Exception as exc:
            _LOG.warning("resolve_pending commit failed: %s", exc)
            session.rollback()

    persist_result: dict[str, Any] = {"ok": False}
    if updated_partial_fit > 0:
        persist_result = _persist_online_model(payload)

    return {
        "ok": True,
        "resolved": resolved_count,
        "correct": correct_count,
        "rolling_accuracy": float(payload.get("rolling_accuracy") or 0.0),
        "samples_seen": int(payload.get("samples_seen") or 0),
        "partial_fit_updates": updated_partial_fit,
        "persisted": persist_result,
    }


def _lookup_actual_from_learning_log(
    session: Any, row: PredictionPending
) -> dict[str, Any] | None:
    """Best-effort lookup of an actual outcome from ``LearningLog``.

    Matches on ``source_id == action_id`` first, then on a ``(user_id,
    action_type)`` window between ``predicted_at`` and ``resolve_after``.
    """
    action_id = (row.action_id or "").strip()
    if action_id and action_id.isdigit():
        try:
            log = session.execute(
                select(LearningLog)
                .where(LearningLog.source_id == int(action_id))
                .order_by(LearningLog.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if log is not None:
                return {
                    "success": bool(log.success) if log.success is not None else None,
                    "outcome": log.outcome,
                    "source": "learning_log_id",
                    "learning_log_id": int(log.id),
                }
        except Exception:
            pass

    if row.action_type and row.user_id is not None:
        stmt = (
            select(LearningLog)
            .where(LearningLog.action_type == str(row.action_type))
            .where(LearningLog.user_id == int(row.user_id))
            .where(LearningLog.created_at >= row.predicted_at)
            .where(LearningLog.created_at <= row.resolve_after + timedelta(hours=12))
            .order_by(LearningLog.created_at.asc())
            .limit(1)
        )
        try:
            log = session.execute(stmt).scalar_one_or_none()
            if log is not None:
                return {
                    "success": bool(log.success) if log.success is not None else None,
                    "outcome": log.outcome,
                    "source": "learning_log_window",
                    "learning_log_id": int(log.id),
                }
        except Exception:
            return None
    return None


# ---------------------------------------------------------------------------
# Drift detection via MiniBatchKMeans
# ---------------------------------------------------------------------------


def online_cluster_features(
    *,
    feature_rows: list[list[float]],
    n_clusters: int = 6,
) -> dict[str, Any]:
    """
    Update an online ``MiniBatchKMeans`` over recent feature rows. Returns the
    cluster centers + inertia. Useful for surfacing "regime shifts" in
    behaviour where the predictor accuracy is likely to degrade.
    """
    if not _SKLEARN_AVAILABLE or MiniBatchKMeans is None or np is None:
        return {"ok": False, "error": "sklearn_missing"}
    if not feature_rows:
        return {"ok": True, "samples": 0, "centers": [], "inertia": None}
    rec = ModelRegistry.get_active(KMEANS_MODEL_NAME) or ModelRegistry.get_latest(KMEANS_MODEL_NAME)
    payload: dict[str, Any] | None = None
    if rec is not None and rec.model_path:
        try:
            payload = joblib.load(rec.model_path)
        except Exception:
            payload = None
    model = payload.get("model") if payload else None
    if model is None:
        model = MiniBatchKMeans(
            n_clusters=max(2, int(n_clusters)),
            random_state=42,
            batch_size=max(8, len(feature_rows)),
            n_init=3,
        )
    X = np.asarray(feature_rows, dtype=float)
    try:
        model.partial_fit(X)
    except Exception as exc:
        return {"ok": False, "error": f"partial_fit_failed: {exc!s}"[:200]}
    new_payload = {
        "model": model,
        "samples_seen": int((payload or {}).get("samples_seen") or 0) + len(feature_rows),
        "n_clusters": int(model.n_clusters),
        "trained_at": _now().isoformat(),
    }
    version = next_version(KMEANS_MODEL_NAME)
    artifact = model_artifact_path(KMEANS_MODEL_NAME, version)
    try:
        joblib.dump(new_payload, artifact)
        ModelRegistry.register(
            name=KMEANS_MODEL_NAME,
            version=version,
            metrics={
                "inertia": float(getattr(model, "inertia_", 0.0) or 0.0),
                "n_clusters": int(model.n_clusters),
                "samples_seen": new_payload["samples_seen"],
            },
            path=str(artifact),
            training_samples=new_payload["samples_seen"],
            notes="online minibatch kmeans",
            activate=True,
        )
    except Exception as exc:
        _LOG.warning("kmeans persist failed: %s", exc)
    return {
        "ok": True,
        "samples": new_payload["samples_seen"],
        "centers": [c.tolist() for c in (model.cluster_centers_ or [])],
        "inertia": float(getattr(model, "inertia_", 0.0) or 0.0),
        "n_clusters": int(model.n_clusters),
        "version": version,
    }


# ---------------------------------------------------------------------------
# Update tracker (called after explicit feedback events)
# ---------------------------------------------------------------------------


def mark_resolved(
    prediction_id: int,
    *,
    actual_outcome: dict[str, Any],
) -> dict[str, Any]:
    """
    Programmatic resolution path: mark a single ``predictions_pending`` row
    resolved and partial-fit the online model.
    """
    factory = _factory_or_none()
    if factory is None:
        return {"ok": False, "error": "no_db"}
    with factory() as session:
        row = session.execute(
            select(PredictionPending).where(PredictionPending.id == int(prediction_id))
        ).scalar_one_or_none()
        if row is None:
            return {"ok": False, "error": "not_found"}
        if row.resolved:
            return {"ok": True, "already_resolved": True}
        partial_ok, label, correct = _resolve_one(session, row, actual_outcome=actual_outcome)
        try:
            session.commit()
        except Exception as exc:
            _LOG.warning("mark_resolved commit failed: %s", exc)
            session.rollback()
            return {"ok": False, "error": f"commit_failed: {exc!s}"[:200]}

    if partial_ok and _SKLEARN_AVAILABLE:
        payload = _ensure_online_model()
        model = payload.get("model")
        if model is not None and label is not None:
            try:
                feats_payload = row.features_json or {}
                feats = list(feats_payload.get("values") or [])
                if feats:
                    X = np.asarray([feats], dtype=float)
                    y = np.asarray([int(label)], dtype=int)
                    model.partial_fit(X, y, classes=np.asarray([0, 1], dtype=int))
                    payload["model"] = model
                    payload["samples_seen"] = int(payload.get("samples_seen") or 0) + 1
                    payload["rolling_correct"] = int(payload.get("rolling_correct") or 0) + int(correct)
                    payload["rolling_total"] = int(payload.get("rolling_total") or 0) + 1
                    payload["rolling_accuracy"] = round(
                        payload["rolling_correct"] / max(payload["rolling_total"], 1), 4
                    )
                    _persist_online_model(payload)
            except Exception as exc:
                _LOG.warning("mark_resolved partial_fit failed: %s", exc)
    return {"ok": True, "label": label, "correct": float(correct)}


# ---------------------------------------------------------------------------
# Status probe (for /personal/os/brain-health and similar)
# ---------------------------------------------------------------------------


def get_status() -> dict[str, Any]:
    """Return a JSON-safe snapshot of the online learner state."""
    payload = _load_online_model() or {}
    return {
        "available": online_available(),
        "samples_seen": int(payload.get("samples_seen") or 0),
        "rolling_accuracy": float(payload.get("rolling_accuracy") or 0.0),
        "rolling_correct": int(payload.get("rolling_correct") or 0),
        "rolling_total": int(payload.get("rolling_total") or 0),
        "version": str(payload.get("version") or ""),
    }


__all__ = [
    "DEFAULT_RESOLVE_HOURS",
    "KMEANS_MODEL_NAME",
    "ONLINE_MODEL_NAME",
    "get_status",
    "mark_resolved",
    "online_available",
    "online_cluster_features",
    "predict_and_record",
    "resolve_pending",
]
