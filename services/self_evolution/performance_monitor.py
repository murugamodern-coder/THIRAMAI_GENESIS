"""Continuous performance monitoring for closed-loop self-improvement.

Reads :class:`core.db.models.LearningLog` rows in configurable time windows.
Unlike the original spec:

* **No ``domain`` column** — domain is taken from ``row.context.get("domain")``,
  matching :mod:`services.counterfactual_engine`.
* **Fair baselines** — default baseline is the *preceding* window of the same
  length as the current window (paired windows). Comparing a 24h window to a
  30d aggregate skewed thresholds; paired windows fixes that.
* **Optional row injection** — ``row_source`` lets tests supply rows without a DB.

Degradation categories (4):

1. ``accuracy_drop`` — decision accuracy down vs baseline by > ``accuracy_threshold``.
2. ``drift`` — aggregate feature-distribution drift score > ``drift_threshold``.
3. ``error_spike`` — error rate vs baseline exceeds ``error_spike_threshold`` multiplier.
4. ``performance_drop`` — trading-domain Sharpe drop > ``sharpe_drop_threshold`` (when both windows have rewards).
"""

from __future__ import annotations

import json
import logging
import threading
import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import LearningLog

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PerformanceMetrics:
    period_start: datetime
    period_end: datetime
    decision_accuracy: float
    prediction_accuracy: float
    feature_drift_score: float
    concept_drift_score: float
    error_rate: float
    avg_confidence: float
    trading_sharpe: float | None
    business_success_rate: float | None
    sample_size: int = 0


@dataclass
class PerformanceDegradation:
    issue_type: str
    severity: float
    affected_domain: str
    affected_component: str
    current_value: float
    baseline_value: float
    threshold: float
    detected_at: datetime
    description: str


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------


def _row_domain(row: Any) -> str:
    ctx = getattr(row, "context", None) or {}
    if isinstance(ctx, dict):
        d = ctx.get("domain")
        if isinstance(d, str) and d.strip():
            return d.strip().lower()
    return "unknown"


def _row_confidence(row: Any) -> float | None:
    payload = getattr(row, "outcome_json", None)
    if isinstance(payload, dict):
        v = payload.get("confidence")
        if isinstance(v, (int, float)):
            return float(v)
    return None


def _learninglog_rows(
    session_factory: Callable[[], Any],
    organization_id: int,
    start: datetime,
    end: datetime,
) -> list[LearningLog]:
    factory = session_factory
    if factory is None:
        return []
    session = factory()
    try:
        stmt = (
            select(LearningLog)
            .where(
                LearningLog.organization_id == int(organization_id),
                LearningLog.created_at >= start,
                LearningLog.created_at < end,
            )
            .order_by(LearningLog.created_at.asc())
        )
        return list(session.scalars(stmt).all())
    except Exception as exc:
        logger.warning("performance_monitor: query failed: %s", exc)
        return []
    finally:
        session.close()


class PerformanceMonitor:
    """Compute metrics and compare paired windows to detect regressions."""

    def __init__(
        self,
        *,
        organization_id: int = 1,
        session_factory: Callable[[], Any] | None = None,
        row_source: Callable[[datetime, datetime], Sequence[Any]] | None = None,
        clock: Callable[[], datetime] | None = None,
        accuracy_threshold: float = 0.10,
        drift_threshold: float = 0.15,
        error_spike_threshold: float = 2.0,
        sharpe_drop_threshold: float = 0.5,
    ) -> None:
        self.organization_id = int(organization_id)
        self._session_factory = session_factory if session_factory is not None else get_session_factory()
        self._row_source = row_source
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.accuracy_threshold = float(accuracy_threshold)
        self.drift_threshold = float(drift_threshold)
        self.error_spike_threshold = float(error_spike_threshold)
        self.sharpe_drop_threshold = float(sharpe_drop_threshold)
        self.baseline_metrics: PerformanceMetrics | None = None

    def check_performance(
        self,
        window_hours: int = 24,
        *,
        refresh_baseline: bool = False,
    ) -> tuple[PerformanceMetrics, list[PerformanceDegradation]]:
        now = self._clock()
        window = max(1, int(window_hours))
        current_end = now
        current_start = now - timedelta(hours=window)
        baseline_end = current_start
        baseline_start = baseline_end - timedelta(hours=window)

        current = self._compute_metrics_slice(current_start, current_end)
        if self.baseline_metrics is None or refresh_baseline:
            self.baseline_metrics = self._compute_metrics_slice(baseline_start, baseline_end)
        degradations = self._detect_degradations(current, self.baseline_metrics)
        if degradations:
            logger.warning("performance_monitor: %d degradation(s) detected", len(degradations))
        return current, degradations

    def set_baseline(self, metrics: PerformanceMetrics) -> None:
        """Inject a baseline (e.g. golden-week snapshot) for tests or ops."""
        self.baseline_metrics = metrics

    def _fetch_rows(self, start: datetime, end: datetime) -> list[Any]:
        if self._row_source is not None:
            return list(self._row_source(start, end))
        if self._session_factory is None:
            return []
        return _learninglog_rows(self._session_factory, self.organization_id, start, end)

    def _compute_metrics_slice(self, start: datetime, end: datetime) -> PerformanceMetrics:
        rows = self._fetch_rows(start, end)
        if not rows:
            return self._empty_metrics(start, end, sample_size=0)
        return self._metrics_from_rows(rows, start, end)

    def _empty_metrics(self, start: datetime, end: datetime, *, sample_size: int) -> PerformanceMetrics:
        return PerformanceMetrics(
            period_start=start,
            period_end=end,
            decision_accuracy=0.0,
            prediction_accuracy=0.0,
            feature_drift_score=0.0,
            concept_drift_score=0.0,
            error_rate=0.0,
            avg_confidence=0.0,
            trading_sharpe=None,
            business_success_rate=None,
            sample_size=sample_size,
        )

    def _metrics_from_rows(
        self,
        rows: Sequence[Any],
        period_start: datetime,
        period_end: datetime,
    ) -> PerformanceMetrics:
        resolved = [r for r in rows if getattr(r, "success", None) is not None]
        if not resolved:
            accuracy = 0.0
            error_rate = 0.0
        else:
            successes = sum(1 for r in resolved if r.success is True)
            failures = sum(1 for r in resolved if r.success is False)
            accuracy = successes / len(resolved)
            error_rate = failures / len(rows) if rows else 0.0

        predictions_ok = 0
        predictions_total = 0
        for r in rows:
            payload = getattr(r, "outcome_json", None)
            if not isinstance(payload, dict):
                continue
            if "predicted" in payload and "actual" in payload:
                predictions_total += 1
                if payload["predicted"] == payload["actual"]:
                    predictions_ok += 1
        prediction_accuracy = (
            predictions_ok / predictions_total if predictions_total else accuracy
        )

        feature_drift = self._scalar_drift_score(rows)
        concept_drift = self._concept_drift_score(rows)

        confidences: list[float] = []
        for r in rows:
            c = _row_confidence(r)
            if c is not None:
                confidences.append(c)
        avg_confidence = float(np.mean(confidences)) if confidences else 0.5

        trading_rows = [r for r in rows if _row_domain(r) == "trading"]
        trading_sharpe = self._trading_sharpe(trading_rows) if trading_rows else None

        business_rows = [r for r in rows if _row_domain(r) == "business"]
        if business_rows:
            br = [r for r in business_rows if r.success is not None]
            business_sr = (
                sum(1 for r in br if r.success is True) / len(br) if br else None
            )
        else:
            business_sr = None

        return PerformanceMetrics(
            period_start=period_start,
            period_end=period_end,
            decision_accuracy=accuracy,
            prediction_accuracy=prediction_accuracy,
            feature_drift_score=feature_drift,
            concept_drift_score=concept_drift,
            error_rate=error_rate,
            avg_confidence=avg_confidence,
            trading_sharpe=trading_sharpe,
            business_success_rate=business_sr,
            sample_size=len(rows),
        )

    def _row_fingerprint(self, row: Any) -> float:
        try:
            ctx = getattr(row, "context", {}) or {}
            inp = getattr(row, "input_data_json", {}) or {}
            blob = json.dumps({"ctx": ctx, "inp": inp}, sort_keys=True, default=str)
            return (zlib.adler32(blob.encode("utf-8")) % 10007) / 10007.0
        except Exception:
            return 0.0

    def _scalar_drift_score(self, rows: Sequence[Any]) -> float:
        """Within-window spread of context fingerprints — high = heterogeneous."""
        if len(rows) < 3:
            return 0.05
        vals = np.array([self._row_fingerprint(r) for r in rows], dtype=float)
        return float(min(1.0, np.std(vals) * 4.0))

    def _concept_drift_score(self, rows: Sequence[Any]) -> float:
        """Compare success rate in first vs second half of the window (chronological)."""
        resolved = [r for r in rows if getattr(r, "success", None) is not None]
        if len(resolved) < 6:
            return 0.08
        mid = len(resolved) // 2
        a = resolved[:mid]
        b = resolved[mid:]
        sa = sum(1 for r in a if r.success is True) / len(a)
        sb = sum(1 for r in b if r.success is True) / len(b)
        return float(min(1.0, abs(sa - sb) * 2.0))

    def _trading_sharpe(self, trading_rows: Sequence[Any]) -> float:
        returns: list[float] = []
        for r in trading_rows:
            payload = getattr(r, "outcome_json", None)
            if isinstance(payload, dict) and payload.get("reward") is not None:
                returns.append(float(payload["reward"]))
        if len(returns) < 2:
            return 0.0
        arr = np.array(returns, dtype=float)
        std = float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0
        if std <= 0:
            return 0.0
        return float(np.mean(arr) / std * np.sqrt(252))

    def _detect_degradations(
        self,
        current: PerformanceMetrics,
        baseline: PerformanceMetrics | None,
    ) -> list[PerformanceDegradation]:
        if baseline is None or baseline.sample_size == 0 or current.sample_size == 0:
            return []

        out: list[PerformanceDegradation] = []
        now = self._clock()

        acc_drop = baseline.decision_accuracy - current.decision_accuracy
        if acc_drop > self.accuracy_threshold and baseline.decision_accuracy > 1e-9:
            out.append(
                PerformanceDegradation(
                    issue_type="accuracy_drop",
                    severity=min(3.0, acc_drop / max(self.accuracy_threshold, 1e-9)),
                    affected_domain="all",
                    affected_component="decision_engine",
                    current_value=current.decision_accuracy,
                    baseline_value=baseline.decision_accuracy,
                    threshold=self.accuracy_threshold,
                    detected_at=now,
                    description=(
                        f"Decision accuracy dropped from {baseline.decision_accuracy:.1%} "
                        f"to {current.decision_accuracy:.1%}"
                    ),
                )
            )

        if current.feature_drift_score > self.drift_threshold:
            out.append(
                PerformanceDegradation(
                    issue_type="drift",
                    severity=min(3.0, current.feature_drift_score / max(self.drift_threshold, 1e-9)),
                    affected_domain="all",
                    affected_component="feature_extraction",
                    current_value=current.feature_drift_score,
                    baseline_value=baseline.feature_drift_score,
                    threshold=self.drift_threshold,
                    detected_at=now,
                    description=(
                        f"Feature footprint drift score {current.feature_drift_score:.2f} "
                        f"(baseline {baseline.feature_drift_score:.2f})"
                    ),
                )
            )

        base_err = max(float(baseline.error_rate), 1e-6)
        err_ratio = current.error_rate / base_err
        if err_ratio > self.error_spike_threshold and current.error_rate > 0:
            out.append(
                PerformanceDegradation(
                    issue_type="error_spike",
                    severity=min(3.0, err_ratio / max(self.error_spike_threshold, 1e-9)),
                    affected_domain="all",
                    affected_component="execution",
                    current_value=current.error_rate,
                    baseline_value=baseline.error_rate,
                    threshold=self.error_spike_threshold,
                    detected_at=now,
                    description=f"Error rate ~{err_ratio:.1f}x baseline",
                )
            )

        if (
            current.trading_sharpe is not None
            and baseline.trading_sharpe is not None
            and baseline.sample_size >= 5
            and current.sample_size >= 5
        ):
            sharpe_drop = baseline.trading_sharpe - current.trading_sharpe
            if sharpe_drop > self.sharpe_drop_threshold:
                out.append(
                    PerformanceDegradation(
                        issue_type="performance_drop",
                        severity=min(3.0, sharpe_drop / max(self.sharpe_drop_threshold, 1e-9)),
                        affected_domain="trading",
                        affected_component="strategy_selector",
                        current_value=current.trading_sharpe,
                        baseline_value=baseline.trading_sharpe,
                        threshold=self.sharpe_drop_threshold,
                        detected_at=now,
                        description=(
                            f"Trading Sharpe dropped from {baseline.trading_sharpe:.2f} "
                            f"to {current.trading_sharpe:.2f}"
                        ),
                    )
                )

        return out


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


_singleton: PerformanceMonitor | None = None
_singleton_lock = threading.Lock()


def get_performance_monitor() -> PerformanceMonitor:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = PerformanceMonitor()
    return _singleton


def reset_performance_monitor() -> None:
    global _singleton
    with _singleton_lock:
        _singleton = None


__all__ = [
    "PerformanceDegradation",
    "PerformanceMetrics",
    "PerformanceMonitor",
    "get_performance_monitor",
    "reset_performance_monitor",
]
