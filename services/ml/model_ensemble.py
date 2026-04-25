"""
Self-Evolution Phase 2: multi-model ensemble.

Trains three classifiers on the same ``LearningLog`` dataset and combines
their predictions with a weight per model derived from each model's recent
accuracy on ``OutcomeFeedback``.

Models
------
1. ``LogisticRegression`` — fast, interpretable.
2. ``RandomForestClassifier`` — robust, non-linear.
3. ``LightGBMClassifier``    — best accuracy when LightGBM is installed
   (gracefully falls back to ``GradientBoostingClassifier`` from sklearn).

Domain → preferred model
------------------------
- ``trading``           → LightGBM
- ``business``          → RandomForest
- ``personal``          → LogisticRegression

The ensemble itself is **also** registered as a model name
(``outcome_predictor_ensemble``) and routes through ``ModelRegistry`` /
``joblib`` like any other artifact.

If ``scikit-learn`` is not available, this module degrades to baseline /
no-op like the rest of the ML stack.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from services.ml import outcome_predictor
from services.ml.model_registry import ModelRegistry, model_artifact_path, next_version

_LOG = logging.getLogger(__name__)

ENSEMBLE_NAME = "outcome_predictor_ensemble"

_ALG_LOGREG = "logistic_regression"
_ALG_RANDOM_FOREST = "random_forest"
_ALG_LIGHTGBM = "lightgbm"

DOMAIN_PREFERRED_MODEL: dict[str, str] = {
    "trading": _ALG_LIGHTGBM,
    "equity_trading": _ALG_LIGHTGBM,
    "business": _ALG_RANDOM_FOREST,
    "irrigation_manufacturing": _ALG_RANDOM_FOREST,
    "edible_oil_production": _ALG_RANDOM_FOREST,
    "agro_trading": _ALG_RANDOM_FOREST,
    "personal_health": _ALG_LOGREG,
    "personal_finance": _ALG_LOGREG,
    "personal_energy": _ALG_LOGREG,
}


# ---------------------------------------------------------------------------
# Optional imports
# ---------------------------------------------------------------------------

try:  # pragma: no cover
    import joblib  # type: ignore[import-not-found]
    from sklearn.ensemble import (  # type: ignore[import-not-found]
        GradientBoostingClassifier,
        RandomForestClassifier,
    )
    from sklearn.linear_model import LogisticRegression  # type: ignore[import-not-found]
    from sklearn.metrics import (  # type: ignore[import-not-found]
        accuracy_score,
        f1_score,
        precision_score,
        recall_score,
    )
    from sklearn.model_selection import train_test_split  # type: ignore[import-not-found]

    _SKLEARN_AVAILABLE = True
except Exception as _exc:  # pragma: no cover
    joblib = None  # type: ignore[assignment]
    GradientBoostingClassifier = None  # type: ignore[assignment]
    RandomForestClassifier = None  # type: ignore[assignment]
    LogisticRegression = None  # type: ignore[assignment]
    accuracy_score = f1_score = precision_score = recall_score = None  # type: ignore[assignment]
    train_test_split = None  # type: ignore[assignment]
    _SKLEARN_AVAILABLE = False
    _LOG.info("scikit-learn unavailable; model_ensemble in baseline mode (%s)", _exc)


def _lightgbm_or_fallback():
    """Return a LightGBM classifier instance or a sklearn GradientBoosting fallback."""
    try:  # pragma: no cover - depends on optional dep
        from lightgbm import LGBMClassifier  # type: ignore[import-not-found]

        return LGBMClassifier(
            n_estimators=200,
            num_leaves=31,
            learning_rate=0.08,
            random_state=42,
            n_jobs=1,
        ), "lightgbm"
    except Exception as exc:
        _LOG.debug("lightgbm unavailable, using GradientBoosting: %s", exc)
        if GradientBoostingClassifier is None:
            return None, "lightgbm_unavailable"
        return GradientBoostingClassifier(
            n_estimators=120, max_depth=4, random_state=42
        ), "gradient_boosting_fallback"


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


def train_ensemble(
    *,
    organization_id: int | None = None,
    lookback_days: int | None = None,
    activate: bool = True,
) -> dict[str, Any]:
    """
    Train all three models on the same dataset and persist a single ensemble
    artifact containing them. Returns a JSON-safe dict with per-model metrics
    plus aggregate ensemble metrics.
    """
    if not _SKLEARN_AVAILABLE:
        return {
            "ok": False,
            "error": "sklearn_missing",
            "version": None,
            "models": {},
            "ensemble_accuracy": 0.0,
            "training_samples": 0,
        }

    lb = int(
        lookback_days
        if lookback_days is not None
        else os.getenv("THIRAMAI_ENSEMBLE_LOOKBACK_DAYS")
        or "180"
    )
    rows = outcome_predictor._load_training_rows(  # noqa: SLF001 - reuse loader
        organization_id=organization_id, lookback_days=lb
    )
    if len(rows) < 50:
        return {
            "ok": False,
            "error": f"insufficient_samples ({len(rows)} < 50)",
            "version": None,
            "models": {},
            "ensemble_accuracy": 0.0,
            "training_samples": len(rows),
        }

    X, y, type_stats = outcome_predictor._build_dataset(rows)  # noqa: SLF001
    if len(set(y)) < 2:
        return {
            "ok": False,
            "error": "single_class_dataset",
            "version": None,
            "models": {},
            "ensemble_accuracy": 0.0,
            "training_samples": len(rows),
        }

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25 if len(X) >= 200 else 0.2, random_state=42, stratify=y
    )

    members: dict[str, Any] = {}
    metrics_by_model: dict[str, dict[str, Any]] = {}

    logreg = LogisticRegression(max_iter=2000)
    logreg.fit(X_train, y_train)
    members[_ALG_LOGREG] = logreg
    metrics_by_model[_ALG_LOGREG] = _eval(logreg, X_test, y_test)

    rf = RandomForestClassifier(
        n_estimators=120, max_depth=8, random_state=42, n_jobs=1, class_weight="balanced"
    )
    rf.fit(X_train, y_train)
    members[_ALG_RANDOM_FOREST] = rf
    metrics_by_model[_ALG_RANDOM_FOREST] = _eval(rf, X_test, y_test)

    lgbm, lgbm_kind = _lightgbm_or_fallback()
    if lgbm is not None:
        try:
            lgbm.fit(X_train, y_train)
            members[_ALG_LIGHTGBM] = lgbm
            metrics_by_model[_ALG_LIGHTGBM] = _eval(lgbm, X_test, y_test)
            metrics_by_model[_ALG_LIGHTGBM]["backend"] = lgbm_kind
        except Exception as exc:
            _LOG.warning("lightgbm/grad-boost fit failed: %s", exc)

    weights = _normalised_weights({k: float(v.get("accuracy") or 0.0) for k, v in metrics_by_model.items()})

    try:
        proba_avg = _ensemble_proba(members, weights, X_test)
        y_pred = [1 if p >= 0.5 else 0 for p in proba_avg]
        ensemble_metrics = {
            "accuracy": float(accuracy_score(y_test, y_pred)),
            "precision": float(precision_score(y_test, y_pred, zero_division=0)),
            "recall": float(recall_score(y_test, y_pred, zero_division=0)),
            "f1": float(f1_score(y_test, y_pred, zero_division=0)),
            "weights": weights,
        }
    except Exception as exc:
        _LOG.warning("ensemble eval failed: %s", exc)
        ensemble_metrics = {"accuracy": 0.0, "weights": weights, "error": str(exc)[:200]}

    version = next_version(ENSEMBLE_NAME)
    artifact = model_artifact_path(ENSEMBLE_NAME, version)
    payload = {
        "members": members,
        "weights": weights,
        "metrics_by_model": metrics_by_model,
        "ensemble_metrics": ensemble_metrics,
        "type_stats": type_stats,
        "feature_names": [
            "action_type_bucket",
            "hour_of_day",
            "day_of_week",
            "inventory_level_norm",
            "revenue_trend_int",
            "past_success_rate",
        ],
        "version": version,
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        joblib.dump(payload, artifact)
    except Exception as exc:
        _LOG.exception("ensemble.persist_failed")
        return {
            "ok": False,
            "error": f"persist_failed: {exc!s}"[:200],
            "version": version,
            "models": metrics_by_model,
            "ensemble_accuracy": float(ensemble_metrics.get("accuracy") or 0.0),
            "training_samples": len(rows),
            "model_path": str(artifact),
        }

    metrics_for_registry = {
        "accuracy": float(ensemble_metrics.get("accuracy") or 0.0),
        "members": list(members.keys()),
        "weights": weights,
        "per_model": metrics_by_model,
        "lookback_days": lb,
    }
    rec = ModelRegistry.register(
        name=ENSEMBLE_NAME,
        version=version,
        metrics=metrics_for_registry,
        path=str(artifact),
        training_samples=len(rows),
        notes=f"organization_id={organization_id}",
        activate=activate,
    )

    return {
        "ok": True,
        "version": version,
        "models": metrics_by_model,
        "ensemble_metrics": ensemble_metrics,
        "ensemble_accuracy": float(ensemble_metrics.get("accuracy") or 0.0),
        "training_samples": len(rows),
        "model_path": str(artifact),
        "registered": rec.to_dict() if rec else None,
        "active": bool(activate),
    }


def _eval(model: Any, X_test: list[list[float]], y_test: list[int]) -> dict[str, Any]:
    y_pred = model.predict(X_test)
    return {
        "accuracy": float(accuracy_score(y_test, y_pred)),
        "precision": float(precision_score(y_test, y_pred, zero_division=0)),
        "recall": float(recall_score(y_test, y_pred, zero_division=0)),
        "f1": float(f1_score(y_test, y_pred, zero_division=0)),
    }


def _normalised_weights(scores: dict[str, float]) -> dict[str, float]:
    """Map per-model accuracies to weights summing to 1.0 (uniform if all zero)."""
    if not scores:
        return {}
    floored = {k: max(0.0, float(v) - 0.5) for k, v in scores.items()}
    total = sum(floored.values())
    if total <= 0.0:
        n = float(len(scores))
        return {k: round(1.0 / n, 6) for k in scores}
    return {k: round(v / total, 6) for k, v in floored.items()}


def _ensemble_proba(
    members: dict[str, Any], weights: dict[str, float], X: list[list[float]]
) -> list[float]:
    if not members:
        return [0.5] * len(X)
    accum = [0.0] * len(X)
    weight_sum = 0.0
    for name, model in members.items():
        w = float(weights.get(name) or 0.0)
        if w <= 0.0:
            continue
        try:
            proba = model.predict_proba(X)
        except Exception:
            continue
        weight_sum += w
        for i, p in enumerate(proba):
            accum[i] += w * float(p[1] if len(p) > 1 else p[0])
    if weight_sum <= 0.0:
        return [0.5] * len(X)
    return [v / weight_sum for v in accum]


# ---------------------------------------------------------------------------
# Predict
# ---------------------------------------------------------------------------


def _load_active_payload() -> dict[str, Any] | None:
    if not _SKLEARN_AVAILABLE or joblib is None:
        return None
    rec = ModelRegistry.get_active(ENSEMBLE_NAME) or ModelRegistry.get_latest(ENSEMBLE_NAME)
    if rec is None or not rec.model_path:
        return None
    try:
        return joblib.load(rec.model_path)
    except Exception as exc:
        _LOG.warning("ensemble.load_failed: %s", exc)
        return None


def select_model_for_domain(domain: str) -> str:
    """Return the preferred algorithm name for a given domain (default RF)."""
    return DOMAIN_PREFERRED_MODEL.get(str(domain or "").strip().lower(), _ALG_RANDOM_FOREST)


def predict(
    *,
    action_type: str,
    when: datetime | None = None,
    context: dict[str, Any] | None = None,
    domain: str | None = None,
    use: str = "ensemble",
) -> dict[str, Any]:
    """
    Predict the success probability of an action via the ensemble.

    ``use`` may be ``"ensemble"`` (weighted average of all members) or one of
    the individual algorithm names (``logistic_regression``, ``random_forest``,
    ``lightgbm``). Domain-specific routing kicks in when ``use="auto"`` and
    ``domain`` is provided.
    """
    when = when or datetime.now(timezone.utc)
    context = context or {}

    payload = _load_active_payload()
    if payload is None:
        return outcome_predictor.predict_success(
            action_type=action_type, when=when, context=context
        )

    type_stats = payload.get("type_stats") or {}
    stats = type_stats.get(str(action_type), {"total": 0, "success": 0})
    total = int(stats.get("total") or 0)
    success = int(stats.get("success") or 0)
    prior = (success / total) if total > 0 else 0.5
    feats = outcome_predictor._row_features(  # noqa: SLF001
        action_type=action_type, when=when, context=context, past_success_rate=prior
    )

    members: dict[str, Any] = payload.get("members") or {}
    weights: dict[str, float] = payload.get("weights") or {}

    chosen = use
    if use == "auto":
        chosen = select_model_for_domain(domain or "")

    if chosen != "ensemble" and chosen in members:
        try:
            proba = members[chosen].predict_proba([feats])[0]
            prob = float(proba[1]) if len(proba) > 1 else float(proba[0])
            return {
                "ok": True,
                "probability": round(max(0.0, min(prob, 1.0)), 4),
                "method": f"single:{chosen}",
                "model_version": str(payload.get("version") or ""),
                "domain": domain,
            }
        except Exception as exc:
            _LOG.debug("single member predict failed for %s: %s", chosen, exc)

    proba = _ensemble_proba(members, weights, [feats])[0] if members else 0.5
    return {
        "ok": True,
        "probability": round(max(0.0, min(proba, 1.0)), 4),
        "method": "ensemble",
        "model_version": str(payload.get("version") or ""),
        "weights": weights,
        "domain": domain,
    }


__all__ = [
    "DOMAIN_PREFERRED_MODEL",
    "ENSEMBLE_NAME",
    "predict",
    "select_model_for_domain",
    "train_ensemble",
]
