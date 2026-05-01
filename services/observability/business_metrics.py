"""Business / system / domain metrics for the live ``/metrics`` endpoint.

This module is *additive* to ``services.observability.decision_metrics``.
``decision_metrics`` is scoped to the PolicyEngine ↔ legacy decision_brain
A/B rollout; ``business_metrics`` is the broader catalogue the Grafana
dashboards under ``monitoring/grafana/dashboards/`` rely on.

Design contract (matches ``decision_metrics.py``):

* ``prometheus_client`` is treated as a **soft dependency**. When it is
  missing every public function is a no-op and metric primitives become
  :class:`_NoOpMetric` stubs. That keeps workers, CLI, and tests usable
  without forcing the optional dep onto every dev box.
* :func:`init_business_metrics` is called from the FastAPI startup handler
  in :mod:`app` and is **idempotent**: re-running it (e.g. on test reload)
  is safe because every individual metric is wrapped in a try/except so the
  Prometheus default registry's "duplicate timeseries" ``ValueError`` is
  swallowed and replaced by a no-op stub for the offending metric.
* No external IO at import time. Everything that touches the DB / Redis /
  broker / OS lives behind a function call.

The :func:`/metrics` endpoint itself is **not** mounted from here — that
already happens in ``app.py`` via ``prometheus_fastapi_instrumentator``.
This module only registers application-level metrics with the same default
registry the instrumentator uses, so they appear on the same scrape.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Soft import of prometheus_client (mirrors decision_metrics)
# ---------------------------------------------------------------------------


class _NoOpMetric:
    """Stub mimicking Prometheus Counter / Histogram / Gauge."""

    def labels(self, *_a: Any, **_kw: Any) -> "_NoOpMetric":
        return self

    def inc(self, *_a: Any, **_kw: Any) -> None:
        return None

    def observe(self, *_a: Any, **_kw: Any) -> None:
        return None

    def set(self, *_a: Any, **_kw: Any) -> None:
        return None


try:  # pragma: no cover - import path differs by env
    from prometheus_client import Counter, Gauge, Histogram

    _PROMETHEUS_AVAILABLE = True
except Exception:  # pragma: no cover
    _PROMETHEUS_AVAILABLE = False
    Counter = Gauge = Histogram = None  # type: ignore[assignment]


def _counter(name: str, doc: str, labels: tuple[str, ...] = ()):
    if not _PROMETHEUS_AVAILABLE:
        return _NoOpMetric()
    try:
        return Counter(name, doc, list(labels))  # type: ignore[arg-type]
    except (ValueError, Exception):
        return _NoOpMetric()


def _gauge(name: str, doc: str, labels: tuple[str, ...] = ()):
    if not _PROMETHEUS_AVAILABLE:
        return _NoOpMetric()
    try:
        return Gauge(name, doc, list(labels))  # type: ignore[arg-type]
    except (ValueError, Exception):
        return _NoOpMetric()


def _histogram(
    name: str,
    doc: str,
    labels: tuple[str, ...] = (),
    buckets: tuple[float, ...] | None = None,
):
    if not _PROMETHEUS_AVAILABLE:
        return _NoOpMetric()
    try:
        kwargs: dict[str, Any] = {}
        if buckets:
            kwargs["buckets"] = list(buckets)
        return Histogram(name, doc, list(labels), **kwargs)  # type: ignore[arg-type]
    except (ValueError, Exception):
        return _NoOpMetric()


# ---------------------------------------------------------------------------
# Latency buckets (seconds and milliseconds)
# ---------------------------------------------------------------------------


_S_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_MS_BUCKETS = (1.0, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 5000.0)
_REWARD_BUCKETS = (-1.0, -0.5, -0.1, 0.0, 0.1, 0.25, 0.5, 0.75, 1.0)


# ---------------------------------------------------------------------------
# Decision metrics (high-level — decision_metrics handles the inner cardinality)
# ---------------------------------------------------------------------------


decision_latency_seconds = _histogram(
    "thiramai_decision_latency_seconds",
    "End-to-end decide() latency.",
    labels=("engine",),
    buckets=_S_BUCKETS,
)
decision_route_total = _counter(
    "thiramai_decision_route_total_v2",
    "Total decisions routed by engine.",
    labels=("engine",),
)
decision_confidence = _gauge(
    "thiramai_decision_confidence_v2",
    "Most recent decision confidence per engine.",
    labels=("engine",),
)
decision_reward = _histogram(
    "thiramai_decision_reward_v2",
    "Realised reward per engine and action.",
    labels=("engine", "action"),
    buckets=_REWARD_BUCKETS,
)
decision_error_total = _counter(
    "thiramai_decision_error_total",
    "Decision errors grouped by error_type.",
    labels=("engine", "error_type"),
)


# ---------------------------------------------------------------------------
# Bandit metrics
# ---------------------------------------------------------------------------


bandit_exploration_rate = _gauge(
    "thiramai_bandit_exploration_rate",
    "Current exploration bonus emitted by the contextual bandit.",
)
bandit_action_count = _gauge(
    "thiramai_bandit_action_count_v2",
    "Selection count per bandit action.",
    labels=("action",),
)
bandit_regret = _gauge(
    "thiramai_bandit_regret",
    "Cumulative bandit regret estimate.",
)
bandit_theta_norm = _gauge(
    "thiramai_bandit_theta_norm",
    "L2 norm of the LinUCB weight vector per action.",
    labels=("action",),
)


# ---------------------------------------------------------------------------
# Trading metrics
# ---------------------------------------------------------------------------


trade_execution_latency_ms = _histogram(
    "thiramai_trade_execution_latency_ms",
    "Order placement latency in milliseconds.",
    labels=("broker", "side"),
    buckets=_MS_BUCKETS,
)
trade_pnl_inr = _gauge(
    "thiramai_trade_pnl_inr",
    "Total PnL (realised + unrealised) in INR.",
    labels=("user_id",),
)
trade_daily_pnl_inr = _gauge(
    "thiramai_trade_daily_pnl_inr",
    "Realised PnL today in INR (resets at IST midnight).",
    labels=("user_id",),
)
trade_position_count = _gauge(
    "thiramai_trade_position_count",
    "Open positions per user.",
    labels=("user_id",),
)
trade_capital_utilization_pct = _gauge(
    "thiramai_trade_capital_utilization_pct",
    "Deployed capital / total capital.",
    labels=("user_id",),
)
trade_win_rate_7d = _gauge(
    "thiramai_trade_win_rate_7d",
    "Rolling 7-day win rate.",
    labels=("user_id",),
)
trade_sharpe_ratio_30d = _gauge(
    "thiramai_trade_sharpe_ratio_30d",
    "Rolling 30-day Sharpe ratio.",
    labels=("user_id",),
)
trade_max_drawdown_pct = _gauge(
    "thiramai_trade_max_drawdown_pct",
    "Current drawdown from 30-day equity peak.",
    labels=("user_id",),
)
trade_kill_switch_active = _gauge(
    "thiramai_trade_kill_switch_active",
    "1 when daily-loss kill-switch is engaged, else 0.",
    labels=("user_id",),
)
trade_broker_errors_total = _counter(
    "thiramai_trade_broker_errors_total",
    "Broker API errors grouped by broker and error type.",
    labels=("broker", "error_type"),
)


# ---------------------------------------------------------------------------
# World model metrics
# ---------------------------------------------------------------------------


world_model_update_latency_ms = _histogram(
    "thiramai_world_model_update_latency_ms",
    "Latency of update_from_observation() in milliseconds.",
    buckets=_MS_BUCKETS,
)
world_model_variable_count = _gauge(
    "thiramai_world_model_variable_count",
    "Number of variables currently tracked.",
)
world_model_evidence_count_total = _counter(
    "thiramai_world_model_evidence_total",
    "Total evidence ticks folded into the belief network.",
)
world_model_prediction_confidence = _histogram(
    "thiramai_world_model_prediction_confidence",
    "Confidence (probability mass on top outcome) of world-model predictions.",
    labels=("outcome",),
    buckets=(0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0),
)


# ---------------------------------------------------------------------------
# Online learner metrics
# ---------------------------------------------------------------------------


online_learner_accuracy = _gauge(
    "thiramai_online_learner_accuracy",
    "Rolling accuracy of the online SGD classifier.",
)
online_learner_drift_score = _gauge(
    "thiramai_online_learner_drift_score",
    "MiniBatchKMeans inertia (higher = more drift).",
)
online_learner_samples_total = _counter(
    "thiramai_online_learner_samples_total",
    "Total samples fed into partial_fit since process start.",
)
online_learner_retrains_total = _counter(
    "thiramai_online_learner_retrains_total",
    "Total registry-versioned retrains performed.",
)


# ---------------------------------------------------------------------------
# System health metrics
# ---------------------------------------------------------------------------


api_request_latency_ms = _histogram(
    "thiramai_api_request_latency_ms",
    "API request latency by endpoint and method.",
    labels=("endpoint", "method"),
    buckets=_MS_BUCKETS,
)
api_error_total = _counter(
    "thiramai_api_error_total",
    "API errors by status_code.",
    labels=("status_code", "endpoint"),
)
worker_queue_depth = _gauge(
    "thiramai_worker_queue_depth",
    "Pending jobs per worker queue.",
    labels=("queue_name",),
)
db_connection_pool_size = _gauge(
    "thiramai_db_connection_pool_size",
    "Active DB connection pool size.",
)
redis_connection_errors_total = _counter(
    "thiramai_redis_connection_errors_total",
    "Redis connection / command errors.",
    labels=("operation",),
)
memory_usage_mb = _gauge(
    "thiramai_memory_usage_mb",
    "Process resident set size in MiB.",
)
cpu_usage_pct = _gauge(
    "thiramai_cpu_usage_pct",
    "Process CPU usage percent (0-100).",
)
process_uptime_seconds = _gauge(
    "thiramai_process_uptime_seconds",
    "Seconds since process start.",
)


# ---------------------------------------------------------------------------
# Risk / business KPI metrics
# ---------------------------------------------------------------------------


risk_var_inr = _gauge(
    "thiramai_risk_var_inr",
    "Value-at-Risk estimate (INR) per user.",
    labels=("user_id",),
)
risk_sector_concentration = _gauge(
    "thiramai_risk_sector_concentration",
    "Largest sector weight in the portfolio (0-1).",
    labels=("user_id",),
)
business_revenue_mtd_inr = _gauge(
    "thiramai_business_revenue_mtd_inr",
    "Month-to-date revenue in INR.",
    labels=("organization_id",),
)
business_inventory_low_stock_count = _gauge(
    "thiramai_business_inventory_low_stock_count",
    "SKUs below reorder point.",
    labels=("organization_id",),
)
business_decisions_today_total = _counter(
    "thiramai_business_decisions_today_total",
    "Decisions logged today (resets daily by external rule).",
    labels=("organization_id",),
)
business_active_users = _gauge(
    "thiramai_business_active_users",
    "Distinct active users in the last 24h.",
)


# ---------------------------------------------------------------------------
# Convenience tracking functions
# ---------------------------------------------------------------------------


def track_api_request(endpoint: str, method: str, latency_ms: float, status_code: int) -> None:
    api_request_latency_ms.labels(endpoint=endpoint, method=method).observe(float(latency_ms))
    if status_code >= 400:
        api_error_total.labels(status_code=str(int(status_code)), endpoint=endpoint).inc()


def track_trade_execution(broker: str, side: str, latency_ms: float) -> None:
    trade_execution_latency_ms.labels(broker=broker, side=side).observe(float(latency_ms))


def track_broker_error(broker: str, error_type: str) -> None:
    trade_broker_errors_total.labels(broker=broker, error_type=error_type).inc()


def track_world_model_update(latency_ms: float) -> None:
    world_model_update_latency_ms.observe(float(latency_ms))
    world_model_evidence_count_total.inc()


def track_world_model_prediction(outcome: str, confidence: float) -> None:
    world_model_prediction_confidence.labels(outcome=outcome).observe(
        max(0.0, min(1.0, float(confidence)))
    )


def track_online_learner_state(*, accuracy: float, samples_seen: int, drift_score: float | None = None) -> None:
    online_learner_accuracy.set(max(0.0, min(1.0, float(accuracy))))
    if samples_seen > 0:
        # Counter cannot be set; we rely on increments elsewhere. Best effort: skip if 0.
        pass
    if drift_score is not None:
        online_learner_drift_score.set(float(drift_score))


def track_bandit_state(actions: dict[str, dict[str, Any]] | None) -> None:
    """Mirror decision_metrics.track_bandit_state but populate the v2 gauges."""
    if not actions:
        return
    for action, stats in actions.items():
        try:
            count = float((stats or {}).get("count") or 0)
            theta_norm = float((stats or {}).get("theta_norm") or 0.0)
            bandit_action_count.labels(action=str(action)).set(count)
            bandit_theta_norm.labels(action=str(action)).set(theta_norm)
        except Exception:  # pragma: no cover - defensive
            continue


def track_kill_switch(user_id: int, active: bool) -> None:
    trade_kill_switch_active.labels(user_id=str(int(user_id))).set(1.0 if active else 0.0)


def track_daily_pnl(user_id: int, pnl_inr: float) -> None:
    trade_daily_pnl_inr.labels(user_id=str(int(user_id))).set(float(pnl_inr))


# ---------------------------------------------------------------------------
# Process / system sampler (lightweight, optional psutil)
# ---------------------------------------------------------------------------


_START_TIME = time.time()

try:  # pragma: no cover - psutil is optional
    import psutil  # type: ignore[import-not-found]

    _PSUTIL_AVAILABLE = True
except Exception:  # pragma: no cover
    psutil = None  # type: ignore[assignment]
    _PSUTIL_AVAILABLE = False


def _sample_process() -> None:
    """One-shot sampler that updates uptime / mem / cpu gauges. Safe to call often."""
    process_uptime_seconds.set(float(time.time() - _START_TIME))
    if not _PSUTIL_AVAILABLE or psutil is None:
        return
    try:
        proc = psutil.Process(os.getpid())
        memory_usage_mb.set(float(proc.memory_info().rss / (1024 * 1024)))
        # cpu_percent(None) = non-blocking; first call returns 0 but subsequent ones are accurate.
        cpu_usage_pct.set(float(proc.cpu_percent(interval=None)))
    except Exception:  # pragma: no cover - defensive
        return


def track_startup() -> None:
    """Mark the moment the API process started — called from FastAPI startup."""
    _sample_process()


# ---------------------------------------------------------------------------
# Public init
# ---------------------------------------------------------------------------


_INITIALISED = False


def init_business_metrics() -> dict[str, Any]:
    """Idempotent metrics init.

    Called from the FastAPI startup handler in :mod:`app`. Safe to call
    multiple times. Returns a small status dict for log lines.
    """
    global _INITIALISED
    if _INITIALISED:
        return {"ok": True, "already_initialised": True, "prometheus": _PROMETHEUS_AVAILABLE}
    _sample_process()
    # Fold in a one-shot world-model variable count for Grafana panels that
    # show "schema size".  Imported lazily so this module stays import-light.
    try:
        from services.world_model.bayesian_world_model import STATE_VARIABLES

        world_model_variable_count.set(float(len(STATE_VARIABLES)))
    except Exception:  # pragma: no cover - defensive
        pass
    _INITIALISED = True
    logger.info(
        "business_metrics initialised prometheus=%s psutil=%s",
        _PROMETHEUS_AVAILABLE,
        _PSUTIL_AVAILABLE,
    )
    return {
        "ok": True,
        "prometheus": _PROMETHEUS_AVAILABLE,
        "psutil": _PSUTIL_AVAILABLE,
    }


def is_prometheus_available() -> bool:
    return _PROMETHEUS_AVAILABLE


__all__ = [
    "api_error_total",
    "api_request_latency_ms",
    "bandit_action_count",
    "bandit_exploration_rate",
    "bandit_regret",
    "bandit_theta_norm",
    "business_active_users",
    "business_decisions_today_total",
    "business_inventory_low_stock_count",
    "business_revenue_mtd_inr",
    "cpu_usage_pct",
    "db_connection_pool_size",
    "decision_confidence",
    "decision_error_total",
    "decision_latency_seconds",
    "decision_reward",
    "decision_route_total",
    "init_business_metrics",
    "is_prometheus_available",
    "memory_usage_mb",
    "online_learner_accuracy",
    "online_learner_drift_score",
    "online_learner_retrains_total",
    "online_learner_samples_total",
    "process_uptime_seconds",
    "redis_connection_errors_total",
    "risk_sector_concentration",
    "risk_var_inr",
    "track_api_request",
    "track_bandit_state",
    "track_broker_error",
    "track_daily_pnl",
    "track_kill_switch",
    "track_online_learner_state",
    "track_startup",
    "track_trade_execution",
    "track_world_model_prediction",
    "track_world_model_update",
    "trade_broker_errors_total",
    "trade_capital_utilization_pct",
    "trade_daily_pnl_inr",
    "trade_execution_latency_ms",
    "trade_kill_switch_active",
    "trade_max_drawdown_pct",
    "trade_pnl_inr",
    "trade_position_count",
    "trade_sharpe_ratio_30d",
    "trade_win_rate_7d",
    "world_model_evidence_count_total",
    "world_model_prediction_confidence",
    "world_model_update_latency_ms",
    "world_model_variable_count",
    "worker_queue_depth",
]
