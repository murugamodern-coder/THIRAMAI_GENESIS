"""
In-process AI decision quality tracker (rolling window).

Used for action/confidence distributions, simple drift vs baseline, and anomaly flags.
Per **worker process** (not shared across Gunicorn workers). For fleet-wide analytics
prefer Prometheus/Grafana (``thiramai_*`` metrics) plus DB audit.
"""

from __future__ import annotations

import logging
import os
import statistics
import threading
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _int_env(*names: str, default: int) -> int:
    for name in names:
        raw = (os.getenv(name) or "").strip()
        if raw:
            try:
                return max(10, int(raw, 10))
            except ValueError:
                continue
    return default


def _float_env(*names: str, default: float) -> float:
    for name in names:
        raw = (os.getenv(name) or "").strip()
        if raw:
            try:
                return float(raw)
            except ValueError:
                continue
    return default


class DecisionQualityTracker:
    """Rolling-window stats for V2 decision payloads (policy arm / source / confidence)."""

    def __init__(self, window_size: int | None = None) -> None:
        self.window_size = window_size or _int_env(
            "THIRAMAI_AI_QUALITY_WINDOW",
            default=1000,
        )
        self._min_baseline = max(20, _int_env("THIRAMAI_AI_QUALITY_MIN_BASELINE", default=100))
        self._low_conf_threshold = _float_env(
            "THIRAMAI_AI_QUALITY_LOW_CONF",
            default=0.1,
        )
        self._drift_delta = _float_env("THIRAMAI_AI_QUALITY_DRIFT_DELTA", default=0.2)
        self._lock = threading.Lock()
        self.recent_decisions: deque[dict[str, Any]] = deque(maxlen=self.window_size)
        self.baseline_action_distribution: dict[str, float] | None = None
        self.baseline_confidence_mean: float | None = None
        self.baseline_confidence_std: float | None = None
        self.anomaly_count = 0
        self.last_anomaly_time: datetime | None = None

    def record_decision(
        self,
        *,
        action: str,
        confidence: float,
        source: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        a = (action or "").strip() or "unknown"
        src = (source or "").strip() or "unknown"
        try:
            conf = float(confidence)
        except (TypeError, ValueError):
            conf = 0.0
        decision: dict[str, Any] = {
            "action": a,
            "confidence": conf,
            "source": src,
            "timestamp": datetime.now(timezone.utc),
            "metadata": dict(metadata or {}),
        }
        with self._lock:
            self.recent_decisions.append(decision)
            n = len(self.recent_decisions)
            if n >= self._min_baseline and self._is_anomaly_unlocked(decision):
                self.anomaly_count += 1
                self.last_anomaly_time = datetime.now(timezone.utc)
                logger.warning(
                    "ai_quality anomaly action=%s conf=%.3f source=%s",
                    a,
                    conf,
                    src,
                )
                try:
                    from services.observability.decision_metrics import track_ai_quality_anomaly

                    track_ai_quality_anomaly()
                except Exception:
                    pass

    def _is_anomaly_unlocked(self, decision: dict[str, Any]) -> bool:
        if decision["confidence"] < self._low_conf_threshold:
            return True
        if self.baseline_action_distribution:
            if decision["action"] not in self.baseline_action_distribution:
                return True
        if (
            self.baseline_confidence_mean is not None
            and self.baseline_confidence_std is not None
            and self.baseline_confidence_std > 1e-9
        ):
            z = abs(
                (decision["confidence"] - float(self.baseline_confidence_mean))
                / float(self.baseline_confidence_std)
            )
            if z > 3.0:
                return True
        return False

    def establish_baseline(self) -> dict[str, Any]:
        with self._lock:
            if len(self.recent_decisions) < self._min_baseline:
                return {
                    "ok": False,
                    "error": f"need>={self._min_baseline} decisions (have {len(self.recent_decisions)})",
                }
            total = len(self.recent_decisions)
            action_ct: dict[str, int] = defaultdict(int)
            for d in self.recent_decisions:
                action_ct[str(d["action"])] += 1
            self.baseline_action_distribution = {
                act: ct / float(total) for act, ct in action_ct.items()
            }
            confidences = [float(d["confidence"]) for d in self.recent_decisions]
            self.baseline_confidence_mean = statistics.mean(confidences)
            self.baseline_confidence_std = (
                statistics.stdev(confidences) if len(confidences) > 1 else 0.0
            )
            logger.info(
                "ai_quality baseline n=%s actions=%s mean_conf=%.3f",
                total,
                list(self.baseline_action_distribution.keys()),
                float(self.baseline_confidence_mean or 0.0),
            )
            return {"ok": True, "sample_size": total}

    def reset_anomaly_count(self) -> None:
        with self._lock:
            self.anomaly_count = 0
            self.last_anomaly_time = None

    def get_quality_metrics(self) -> dict[str, Any]:
        with self._lock:
            if not self.recent_decisions:
                return {"status": "no_data"}

            total_decisions = len(self.recent_decisions)
            action_ct: dict[str, int] = defaultdict(int)
            source_ct: dict[str, int] = defaultdict(int)
            confidences: list[float] = []
            for d in self.recent_decisions:
                action_ct[str(d["action"])] += 1
                source_ct[str(d["source"])] += 1
                confidences.append(float(d["confidence"]))

            action_dist = {a: c / float(total_decisions) for a, c in action_ct.items()}
            source_dist = {s: c / float(total_decisions) for s, c in source_ct.items()}
            conf_mean = statistics.mean(confidences) if confidences else 0.0
            conf_std = statistics.stdev(confidences) if len(confidences) > 1 else 0.0

            drift_detected = False
            drift_details: dict[str, Any] = {}
            if self.baseline_action_distribution:
                for act, base_p in self.baseline_action_distribution.items():
                    cur_p = action_dist.get(act, 0.0)
                    delta = abs(cur_p - base_p)
                    if delta > self._drift_delta:
                        drift_detected = True
                        drift_details[act] = {
                            "baseline": base_p,
                            "current": cur_p,
                            "change": delta,
                        }

            return {
                "status": "ok",
                "window_cap": self.window_size,
                "window_size": total_decisions,
                "action_distribution": action_dist,
                "source_distribution": source_dist,
                "confidence": {
                    "mean": conf_mean,
                    "std": conf_std,
                    "min": min(confidences) if confidences else 0.0,
                    "max": max(confidences) if confidences else 0.0,
                },
                "baseline": {
                    "action_distribution": self.baseline_action_distribution,
                    "confidence_mean": self.baseline_confidence_mean,
                    "confidence_std": self.baseline_confidence_std,
                },
                "anomalies": {
                    "count": self.anomaly_count,
                    "last_seen": self.last_anomaly_time.isoformat()
                    if self.last_anomaly_time
                    else None,
                },
                "drift": {"detected": drift_detected, "details": drift_details},
            }


_tracker: DecisionQualityTracker | None = None
_tracker_lock = threading.Lock()


def get_quality_tracker() -> DecisionQualityTracker:
    global _tracker
    with _tracker_lock:
        if _tracker is None:
            _tracker = DecisionQualityTracker()
        return _tracker


def reset_quality_tracker_for_tests() -> None:
    global _tracker
    with _tracker_lock:
        _tracker = None


__all__ = [
    "DecisionQualityTracker",
    "get_quality_tracker",
    "reset_quality_tracker_for_tests",
]
