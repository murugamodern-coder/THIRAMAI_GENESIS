"""Meta-Learning — Self-Evolution Phase 4 Task 3.

The meta-learner answers four questions across the registered domains:

1. **Which features matter most per domain?**
   We refit a small RandomForest on each domain's recent
   :class:`~core.db.models.LearningLog` rows and store
   ``feature_importances_``.

2. **Which model type works best per context?**
   Using resolved :class:`~core.db.models.PredictionPending` rows we compute
   per-(domain, time-of-day-bucket) accuracy for every model that has shipped
   predictions, and pick a winner per bucket.

3. **Which time of day is best for decisions?**
   Aggregate ``LearningLog`` success rate by hour-of-day per domain and
   surface the top hours as the recommended decision window.

4. **Auto-tune hyperparameters.**
   A bounded random search over a sklearn HP grid, validated by a held-out
   split of the same dataset used in (1).

Outputs are persisted as :class:`~core.db.models.MetaLearningRecord` rows.
The most recent ``is_recommendation=True`` row per ``(domain, record_type)``
is what downstream services consume via :func:`get_recommended_setup`.

Sklearn is **optional**. If unavailable the engine still emits time-of-day
records and surfaces ``ok=False`` payloads for the rest, with no exceptions.
"""

from __future__ import annotations

import logging
import os
import random
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import select

from core.db.models import (
    LearningLog,
    MetaLearningRecord,
    PredictionPending,
)

_LOG = logging.getLogger(__name__)

# Default lookback / sampling knobs (env-overridable for tests).
_DEFAULT_FI_LOOKBACK_DAYS = int(os.getenv("THIRAMAI_META_FI_LOOKBACK_DAYS") or "60")
_DEFAULT_TIME_LOOKBACK_DAYS = int(os.getenv("THIRAMAI_META_TIME_LOOKBACK_DAYS") or "45")
_DEFAULT_MODEL_LOOKBACK_DAYS = int(os.getenv("THIRAMAI_META_MODEL_LOOKBACK_DAYS") or "30")
_DEFAULT_HP_TRIALS = int(os.getenv("THIRAMAI_META_HP_TRIALS") or "8")
_MIN_SAMPLES_FOR_FI = 30
_MIN_SAMPLES_PER_BUCKET = 8
_MIN_SAMPLES_FOR_HP = 50

_REC_FEATURE_IMPORTANCE = "feature_importance"
_REC_MODEL_CHOICE = "model_choice"
_REC_TIME_OF_DAY = "time_of_day"
_REC_HYPERPARAMETERS = "hyperparameters"

_TIME_BUCKETS = (
    ("night", range(0, 6)),
    ("morning", range(6, 12)),
    ("afternoon", range(12, 17)),
    ("evening", range(17, 22)),
    ("late_night", range(22, 24)),
)


# ---------------------------------------------------------------------------
# Optional sklearn
# ---------------------------------------------------------------------------

try:  # pragma: no cover - depends on optional dep
    from sklearn.ensemble import RandomForestClassifier  # type: ignore[import-not-found]
    from sklearn.linear_model import LogisticRegression  # type: ignore[import-not-found]
    from sklearn.metrics import accuracy_score  # type: ignore[import-not-found]
    from sklearn.model_selection import train_test_split  # type: ignore[import-not-found]

    _SKLEARN_AVAILABLE = True
except Exception as _exc:  # pragma: no cover - missing dep
    RandomForestClassifier = None  # type: ignore[assignment]
    LogisticRegression = None  # type: ignore[assignment]
    accuracy_score = None  # type: ignore[assignment]
    train_test_split = None  # type: ignore[assignment]
    _SKLEARN_AVAILABLE = False
    _LOG.info("scikit-learn unavailable; meta_learner in degraded mode (%s)", _exc)


def sklearn_available() -> bool:
    return bool(_SKLEARN_AVAILABLE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _factory_or_none():
    try:
        from core.database import get_session_factory

        return get_session_factory()
    except Exception:
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _domain_names() -> list[str]:
    """Return active domain names; falls back to a sane default list."""
    try:
        from core.domains.domain_registry import DomainRegistry

        names = [d.name for d in DomainRegistry.list_all(active_only=True)]
        if names:
            return names
    except Exception:
        pass
    return [
        "irrigation_manufacturing",
        "edible_oil_production",
        "agro_trading",
        "equity_trading",
        "personal_health",
        "personal_finance",
    ]


def _domain_for_log(row: LearningLog) -> str:
    """Best-effort attribution of a learning-log row to a domain."""
    ctx = row.context if isinstance(row.context, dict) else {}
    raw = ctx.get("domain") or ctx.get("module") or ctx.get("category")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower().replace("-", "_")
    atype = str(row.action_type or "").lower()
    if "trade" in atype or "stock" in atype or "equity" in atype:
        return "equity_trading"
    if "inventory" in atype or "manufactur" in atype:
        return "irrigation_manufacturing"
    if "oil" in atype or "jaggery" in atype or "production" in atype:
        return "edible_oil_production"
    if "agri" in atype or "agro" in atype or "trading_crop" in atype:
        return "agro_trading"
    if "health" in atype or "habit" in atype:
        return "personal_health"
    if "finance" in atype or "expense" in atype or "billing" in atype:
        return "personal_finance"
    return "general"


def _time_bucket(when: datetime | None) -> str:
    if when is None:
        return "unknown"
    hour = int(when.hour)
    for label, span in _TIME_BUCKETS:
        if hour in span:
            return label
    return "unknown"


def _build_dataset_for_domain(
    domain: str, *, lookback_days: int
) -> tuple[list[list[float]], list[int], list[str]]:
    """Return (X, y, feature_names) for a domain. Uses outcome_predictor's feature builder."""
    try:
        from services.ml.outcome_predictor import _build_dataset, _load_training_rows  # noqa: SLF001
    except Exception as exc:
        _LOG.debug("meta_learner outcome_predictor import failed: %s", exc)
        return [], [], []

    factory = _factory_or_none()
    if factory is None:
        return [], [], []
    rows = _load_training_rows(None, int(lookback_days))
    rows = [r for r in rows if _domain_for_log(r) == domain]
    if not rows:
        return [], [], []
    X, y, _ = _build_dataset(rows)
    feature_names = [
        "action_type_bucket",
        "hour_of_day",
        "day_of_week",
        "inventory_level_norm",
        "revenue_trend",
        "past_success_rate",
    ]
    return X, y, feature_names


# ---------------------------------------------------------------------------
# Persistence helper
# ---------------------------------------------------------------------------


def _persist_record(
    *,
    organization_id: int | None,
    domain: str,
    record_type: str,
    subject: str,
    payload: dict[str, Any],
    score: float,
    sample_count: int,
    is_recommendation: bool,
) -> int | None:
    factory = _factory_or_none()
    if factory is None:
        return None
    try:
        with factory() as session:
            row = MetaLearningRecord(
                organization_id=organization_id,
                domain=str(domain)[:128],
                record_type=str(record_type)[:64],
                subject=str(subject or "")[:255],
                payload=dict(payload or {}),
                score=float(score),
                sample_count=int(sample_count),
                is_recommendation=bool(is_recommendation),
            )
            session.add(row)
            session.commit()
            return int(row.id)
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("meta_learner persist failed type=%s domain=%s err=%s", record_type, domain, exc)
        return None


# ---------------------------------------------------------------------------
# 1. Feature importance per domain
# ---------------------------------------------------------------------------


def analyze_feature_importance(
    domain: str,
    *,
    organization_id: int | None = None,
    lookback_days: int = _DEFAULT_FI_LOOKBACK_DAYS,
) -> dict[str, Any]:
    if not _SKLEARN_AVAILABLE or RandomForestClassifier is None:
        return {"ok": False, "domain": domain, "error": "sklearn_unavailable"}

    X, y, feature_names = _build_dataset_for_domain(domain, lookback_days=lookback_days)
    if len(X) < _MIN_SAMPLES_FOR_FI or len(set(y)) < 2:
        return {
            "ok": False,
            "domain": domain,
            "error": "insufficient_data",
            "samples": len(X),
        }

    clf = RandomForestClassifier(
        n_estimators=120,
        max_depth=6,
        random_state=42,
        n_jobs=1,
        class_weight="balanced",
    )
    try:
        clf.fit(X, y)
    except Exception as exc:
        return {"ok": False, "domain": domain, "error": f"fit_failed: {exc}"}

    importances = list(clf.feature_importances_)
    pairs = sorted(zip(feature_names, importances), key=lambda kv: kv[1], reverse=True)
    top = [{"feature": name, "importance": round(float(score), 6)} for name, score in pairs]

    record_id = _persist_record(
        organization_id=organization_id,
        domain=domain,
        record_type=_REC_FEATURE_IMPORTANCE,
        subject="random_forest_feature_importance",
        payload={"importances": top, "feature_names": feature_names},
        score=float(top[0]["importance"]) if top else 0.0,
        sample_count=len(X),
        is_recommendation=True,
    )
    return {
        "ok": True,
        "domain": domain,
        "samples": len(X),
        "top_features": top,
        "record_id": record_id,
    }


# ---------------------------------------------------------------------------
# 2. Best model per (domain, time-of-day) bucket
# ---------------------------------------------------------------------------


def analyze_model_performance_by_context(
    *,
    organization_id: int | None = None,
    lookback_days: int = _DEFAULT_MODEL_LOOKBACK_DAYS,
) -> dict[str, Any]:
    factory = _factory_or_none()
    if factory is None:
        return {"ok": False, "error": "no_db"}

    since = _now() - timedelta(days=int(lookback_days))
    try:
        with factory() as session:
            stmt = (
                select(PredictionPending)
                .where(PredictionPending.resolved.is_(True))
                .where(PredictionPending.predicted_at >= since)
                .limit(20_000)
            )
            rows = list(session.execute(stmt).scalars().all())
    except Exception as exc:
        _LOG.debug("meta_learner predictions_pending unavailable: %s", exc)
        return {"ok": False, "error": str(exc)}

    if not rows:
        return {"ok": False, "error": "no_resolved_predictions", "samples": 0}

    # bucket: domain → time_of_day → model_name → list[accuracy]
    bucket: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    sample_counts: Counter[tuple[str, str]] = Counter()
    for r in rows:
        ctx = r.features_json if isinstance(r.features_json, dict) else {}
        domain = ctx.get("domain") or ctx.get("module") or "general"
        if isinstance(domain, str):
            domain_key = domain.strip().lower().replace("-", "_") or "general"
        else:
            domain_key = "general"
        bucket_label = _time_bucket(r.predicted_at)
        model = (r.model_name or "unknown").strip() or "unknown"
        bucket[(domain_key, bucket_label, model)].append(float(r.accuracy_score or 0.0))
        sample_counts[(domain_key, bucket_label)] += 1

    recommendations: list[dict[str, Any]] = []
    by_bucket: dict[tuple[str, str], list[tuple[str, float, int]]] = defaultdict(list)
    for (domain_key, bucket_label, model), scores in bucket.items():
        if len(scores) < _MIN_SAMPLES_PER_BUCKET:
            continue
        avg = sum(scores) / len(scores)
        by_bucket[(domain_key, bucket_label)].append((model, float(avg), len(scores)))

    for (domain_key, bucket_label), entries in by_bucket.items():
        entries.sort(key=lambda kv: kv[1], reverse=True)
        winner_model, winner_acc, winner_n = entries[0]
        record_id = _persist_record(
            organization_id=organization_id,
            domain=domain_key,
            record_type=_REC_MODEL_CHOICE,
            subject=f"{bucket_label}::{winner_model}",
            payload={
                "time_bucket": bucket_label,
                "ranking": [
                    {"model": m, "accuracy": round(a, 4), "samples": n}
                    for m, a, n in entries[:5]
                ],
            },
            score=winner_acc,
            sample_count=winner_n,
            is_recommendation=True,
        )
        recommendations.append(
            {
                "domain": domain_key,
                "time_bucket": bucket_label,
                "best_model": winner_model,
                "accuracy": round(winner_acc, 4),
                "samples": winner_n,
                "record_id": record_id,
            }
        )

    return {
        "ok": True,
        "samples": len(rows),
        "buckets_analysed": len(by_bucket),
        "recommendations": recommendations,
    }


# ---------------------------------------------------------------------------
# 3. Best decision time per domain
# ---------------------------------------------------------------------------


def analyze_optimal_decision_time(
    *,
    organization_id: int | None = None,
    lookback_days: int = _DEFAULT_TIME_LOOKBACK_DAYS,
) -> dict[str, Any]:
    factory = _factory_or_none()
    if factory is None:
        return {"ok": False, "error": "no_db"}

    since = _now() - timedelta(days=int(lookback_days))
    try:
        with factory() as session:
            stmt = (
                select(LearningLog)
                .where(LearningLog.created_at >= since)
                .limit(40_000)
            )
            rows = list(session.execute(stmt).scalars().all())
    except Exception as exc:
        _LOG.debug("meta_learner learning_logs unavailable: %s", exc)
        return {"ok": False, "error": str(exc)}

    # domain → bucket_label → (success_count, total)
    counts: dict[str, dict[str, list[int]]] = defaultdict(
        lambda: {label: [0, 0] for label, _ in _TIME_BUCKETS}
    )
    for r in rows:
        domain = _domain_for_log(r)
        bucket_label = _time_bucket(r.created_at)
        if bucket_label not in counts[domain]:
            counts[domain][bucket_label] = [0, 0]
        counts[domain][bucket_label][1] += 1
        if (r.success is True) or str(r.outcome or "").lower() in (
            "success",
            "ok",
            "approved",
            "applied",
        ):
            counts[domain][bucket_label][0] += 1

    recommendations: list[dict[str, Any]] = []
    for domain, bucket_data in counts.items():
        ranked: list[tuple[str, float, int]] = []
        total_samples = 0
        for bucket_label, (succ, total) in bucket_data.items():
            total_samples += total
            if total < _MIN_SAMPLES_PER_BUCKET:
                continue
            ranked.append((bucket_label, succ / total, total))
        if not ranked:
            continue
        ranked.sort(key=lambda kv: kv[1], reverse=True)
        winner = ranked[0]
        record_id = _persist_record(
            organization_id=organization_id,
            domain=domain,
            record_type=_REC_TIME_OF_DAY,
            subject=winner[0],
            payload={
                "ranking": [
                    {"bucket": b, "success_rate": round(r, 4), "samples": n}
                    for b, r, n in ranked[:5]
                ]
            },
            score=float(winner[1]),
            sample_count=winner[2],
            is_recommendation=True,
        )
        recommendations.append(
            {
                "domain": domain,
                "best_bucket": winner[0],
                "success_rate": round(winner[1], 4),
                "samples": winner[2],
                "record_id": record_id,
                "total_samples": total_samples,
            }
        )

    return {
        "ok": True,
        "samples": len(rows),
        "domains_analysed": len(counts),
        "recommendations": recommendations,
    }


# ---------------------------------------------------------------------------
# 4. Auto-tune hyperparameters
# ---------------------------------------------------------------------------


def _hp_grid_for(model_name: str) -> list[dict[str, Any]]:
    if model_name == "random_forest":
        return [
            {"n_estimators": n, "max_depth": d, "min_samples_split": ms}
            for n in (80, 120, 200)
            for d in (4, 6, 10)
            for ms in (2, 4, 8)
        ]
    if model_name == "logistic_regression":
        return [
            {"C": c, "max_iter": mi, "penalty": p}
            for c in (0.1, 0.5, 1.0, 3.0, 10.0)
            for mi in (200, 500)
            for p in ("l2",)
        ]
    return []


def _instantiate(model_name: str, hp: dict[str, Any]):
    if not _SKLEARN_AVAILABLE:
        return None
    if model_name == "random_forest" and RandomForestClassifier is not None:
        return RandomForestClassifier(
            random_state=42, n_jobs=1, class_weight="balanced", **hp
        )
    if model_name == "logistic_regression" and LogisticRegression is not None:
        return LogisticRegression(
            random_state=42,
            class_weight="balanced",
            solver="lbfgs",
            **hp,
        )
    return None


def auto_tune_hyperparameters(
    domain: str,
    *,
    model_name: str = "random_forest",
    organization_id: int | None = None,
    n_trials: int = _DEFAULT_HP_TRIALS,
) -> dict[str, Any]:
    if not _SKLEARN_AVAILABLE or accuracy_score is None or train_test_split is None:
        return {"ok": False, "domain": domain, "error": "sklearn_unavailable"}

    X, y, _ = _build_dataset_for_domain(domain, lookback_days=_DEFAULT_FI_LOOKBACK_DAYS)
    if len(X) < _MIN_SAMPLES_FOR_HP or len(set(y)) < 2:
        return {
            "ok": False,
            "domain": domain,
            "error": "insufficient_data",
            "samples": len(X),
        }

    grid = _hp_grid_for(model_name)
    if not grid:
        return {"ok": False, "domain": domain, "error": f"no_hp_grid_for_{model_name}"}

    rng = random.Random(42)
    sampled = rng.sample(grid, k=min(int(n_trials), len(grid)))

    try:
        X_tr, X_te, y_tr, y_te = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y if len(set(y)) > 1 else None
        )
    except Exception:
        X_tr, X_te, y_tr, y_te = X, X, y, y

    results: list[dict[str, Any]] = []
    best: tuple[float, dict[str, Any]] | None = None
    for hp in sampled:
        clf = _instantiate(model_name, hp)
        if clf is None:
            continue
        try:
            clf.fit(X_tr, y_tr)
            preds = clf.predict(X_te)
            acc = float(accuracy_score(y_te, preds))
        except Exception as exc:
            _LOG.debug("meta_learner HP trial failed model=%s hp=%s err=%s", model_name, hp, exc)
            continue
        results.append({"hp": hp, "accuracy": round(acc, 4)})
        if best is None or acc > best[0]:
            best = (acc, hp)

    if best is None:
        return {"ok": False, "domain": domain, "error": "all_trials_failed"}

    record_id = _persist_record(
        organization_id=organization_id,
        domain=domain,
        record_type=_REC_HYPERPARAMETERS,
        subject=f"{model_name}::tuned",
        payload={
            "model_name": model_name,
            "best_hp": best[1],
            "trials": results,
        },
        score=float(best[0]),
        sample_count=len(X),
        is_recommendation=True,
    )
    return {
        "ok": True,
        "domain": domain,
        "model_name": model_name,
        "best_hp": best[1],
        "accuracy": round(best[0], 4),
        "trials": len(results),
        "samples": len(X),
        "record_id": record_id,
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_full_meta_cycle(
    *,
    organization_id: int | None = None,
    domains: Iterable[str] | None = None,
    tune_hp_for: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Run all four analyses across the registered domains.

    ``tune_hp_for`` is the (small) subset of domains for which an HP search is
    actually executed — HP tuning is the heaviest step, so by default it only
    runs for one or two domains the caller picks.
    """
    domain_list = list(domains) if domains is not None else _domain_names()
    tune_set = set(tune_hp_for or [])

    results: dict[str, Any] = {
        "started_at": _now().isoformat(),
        "domains": domain_list,
        "feature_importance": {},
        "hyperparameters": {},
    }

    for domain in domain_list:
        results["feature_importance"][domain] = analyze_feature_importance(
            domain, organization_id=organization_id
        )

    results["model_choice"] = analyze_model_performance_by_context(
        organization_id=organization_id
    )
    results["time_of_day"] = analyze_optimal_decision_time(organization_id=organization_id)

    for domain in tune_set:
        if domain not in domain_list:
            continue
        results["hyperparameters"][domain] = auto_tune_hyperparameters(
            domain, organization_id=organization_id
        )

    results["finished_at"] = _now().isoformat()
    return results


# ---------------------------------------------------------------------------
# Read APIs (consumed by downstream services / dashboards)
# ---------------------------------------------------------------------------


def _latest_recommendation(
    domain: str, record_type: str, *, organization_id: int | None = None
) -> MetaLearningRecord | None:
    factory = _factory_or_none()
    if factory is None:
        return None
    try:
        with factory() as session:
            stmt = (
                select(MetaLearningRecord)
                .where(MetaLearningRecord.domain == domain)
                .where(MetaLearningRecord.record_type == record_type)
                .where(MetaLearningRecord.is_recommendation.is_(True))
            )
            if organization_id is not None:
                stmt = stmt.where(MetaLearningRecord.organization_id == int(organization_id))
            stmt = stmt.order_by(
                MetaLearningRecord.captured_at.desc(), MetaLearningRecord.id.desc()
            ).limit(1)
            return session.execute(stmt).scalars().first()
    except Exception:
        return None


def get_recommended_setup(
    domain: str, *, organization_id: int | None = None
) -> dict[str, Any]:
    """Return the latest recommendations across all four record types for ``domain``.

    Useful for downstream callers (predictor, decision engine) that just want
    "give me the best knobs for this domain right now".
    """
    out: dict[str, Any] = {"domain": domain, "ok": True}
    for rtype in (
        _REC_FEATURE_IMPORTANCE,
        _REC_MODEL_CHOICE,
        _REC_TIME_OF_DAY,
        _REC_HYPERPARAMETERS,
    ):
        rec = _latest_recommendation(domain, rtype, organization_id=organization_id)
        if rec is None:
            out[rtype] = None
            continue
        out[rtype] = {
            "subject": rec.subject,
            "score": round(float(rec.score or 0.0), 4),
            "sample_count": int(rec.sample_count or 0),
            "captured_at": rec.captured_at.isoformat() if rec.captured_at else None,
            "payload": rec.payload or {},
        }
    return out


def get_meta_score() -> int:
    """Overall maturity: 0-100. Counts active recommendations across domains."""
    factory = _factory_or_none()
    if factory is None:
        return 0
    try:
        with factory() as session:
            from sqlalchemy import func as _func

            stmt = select(_func.count(MetaLearningRecord.id)).where(
                MetaLearningRecord.is_recommendation.is_(True)
            )
            n = int(session.execute(stmt).scalars().first() or 0)
    except Exception:
        return 0
    # 6 domains × 4 record types = 24 ideal active recs. Cap at 100.
    return int(min(100, round(n / 24.0 * 100)))


def get_status() -> dict[str, Any]:
    """Capability snapshot for ``GET /personal/os/brain-health``."""
    factory = _factory_or_none()
    counts: dict[str, int] = {}
    last_at: str | None = None
    if factory is not None:
        try:
            with factory() as session:
                from sqlalchemy import func as _func

                stmt = select(
                    MetaLearningRecord.record_type, _func.count()
                ).group_by(MetaLearningRecord.record_type)
                counts = {str(rt): int(n) for rt, n in session.execute(stmt).all()}
                last = (
                    session.execute(
                        select(MetaLearningRecord.captured_at)
                        .order_by(MetaLearningRecord.captured_at.desc())
                        .limit(1)
                    )
                    .scalars()
                    .first()
                )
                if last is not None:
                    last_at = last.isoformat()
        except Exception:
            pass
    return {
        "sklearn_available": sklearn_available(),
        "record_counts": counts,
        "last_record_at": last_at,
        "meta_score": get_meta_score(),
        "domains_known": len(_domain_names()),
    }


__all__ = [
    "analyze_feature_importance",
    "analyze_model_performance_by_context",
    "analyze_optimal_decision_time",
    "auto_tune_hyperparameters",
    "get_meta_score",
    "get_recommended_setup",
    "get_status",
    "run_full_meta_cycle",
    "sklearn_available",
]
