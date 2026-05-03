"""
Prometheus metrics for the PolicyEngine ↔ legacy decision_brain A/B rollout.

Why this module exists in *addition* to ``ab_test_metrics.py``:

* ``ab_test_metrics.py`` does **historical** comparison — read-only DB queries
  over ``learning_logs``.
* ``decision_metrics.py`` does **live** observability — Prometheus counters /
  histograms / gauges scraped by the ``/metrics`` endpoint that
  ``prometheus_fastapi_instrumentator`` already exposes from ``app.py``.

The module is import-safe even when ``prometheus_client`` is not installed:
all metric primitives degrade to no-op stubs, and every public function
silently does nothing. That keeps non-API callers (workers, CLI, tests) from
failing just because the optional dep is missing.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from functools import wraps
from typing import Any, Callable, Mapping

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prometheus client — soft dependency
# ---------------------------------------------------------------------------


class _NoOpMetric:
    """Stub that mimics Prometheus Counter / Histogram / Gauge."""

    def labels(self, *_a: Any, **_kw: Any) -> "_NoOpMetric":
        return self

    def inc(self, *_a: Any, **_kw: Any) -> None:  # noqa: D401
        return None

    def observe(self, *_a: Any, **_kw: Any) -> None:  # noqa: D401
        return None

    def set(self, *_a: Any, **_kw: Any) -> None:  # noqa: D401
        return None


try:  # pragma: no cover - import path differs in environments without the dep
    from prometheus_client import Counter, Gauge, Histogram

    _PROMETHEUS_AVAILABLE = True
except Exception:  # pragma: no cover
    _PROMETHEUS_AVAILABLE = False
    Counter = Gauge = Histogram = None  # type: ignore[assignment]


def _counter(name: str, doc: str, labels: tuple[str, ...]):
    if _PROMETHEUS_AVAILABLE:
        try:
            return Counter(name, doc, list(labels))  # type: ignore[arg-type]
        except ValueError:
            # Re-import in tests resets the module but the registry persists.
            return _NoOpMetric()
    return _NoOpMetric()


def _histogram(name: str, doc: str, labels: tuple[str, ...], buckets: tuple[float, ...]):
    if _PROMETHEUS_AVAILABLE:
        try:
            return Histogram(name, doc, list(labels), buckets=list(buckets))  # type: ignore[arg-type]
        except ValueError:
            return _NoOpMetric()
    return _NoOpMetric()


def _gauge(name: str, doc: str, labels: tuple[str, ...] = ()):
    if _PROMETHEUS_AVAILABLE:
        try:
            return Gauge(name, doc, list(labels))  # type: ignore[arg-type]
        except ValueError:
            return _NoOpMetric()
    return _NoOpMetric()


# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------


decision_route_counter = _counter(
    "thiramai_decision_route_total",
    "Decisions routed by engine.",
    ("engine",),
)

decision_latency_histogram = _histogram(
    "thiramai_decision_latency_seconds",
    "Decision latency in seconds.",
    ("engine",),
    (0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
)

action_counter = _counter(
    "thiramai_decision_action_total",
    "Actions chosen, labeled by engine.",
    ("engine", "action"),
)

confidence_gauge = _gauge(
    "thiramai_decision_confidence",
    "Most recent decision confidence score.",
    ("engine",),
)

reward_histogram = _histogram(
    "thiramai_decision_reward",
    "Observed reward per resolved decision.",
    ("engine", "action"),
    (-1.0, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0),
)

exploration_gauge = _gauge(
    "thiramai_policy_exploration_bonus",
    "Most recent PolicyEngine exploration bonus.",
)

bandit_action_count = _gauge(
    "thiramai_bandit_action_count",
    "Cumulative selection count per bandit arm.",
    ("action",),
)

policy_engine_circuit_state = _gauge(
    "thiramai_policy_engine_circuit_state",
    "PolicyEngine circuit: 0=closed, 1=open, 2=half-open, -1=unknown.",
)

safe_fallback_decisions_total = _counter(
    "thiramai_safe_fallback_decisions_total",
    "In-process safe_fallback decisions (degraded mode).",
    (),
)

policy_engine_wrapped_success_total = _counter(
    "thiramai_policy_engine_wrapped_success_total",
    "Successful PolicyEngine.decide calls after circuit breaker.",
    (),
)

ai_quality_anomaly_total = _counter(
    "thiramai_ai_quality_anomalies_total",
    "In-process AI quality tracker anomaly flags.",
    (),
)


# ---------------------------------------------------------------------------
# Public tracking API
# ---------------------------------------------------------------------------


policy_engine_failure_total = _counter(
    "thiramai_policy_engine_failures_total",
    "PolicyEngine.decide raised before optional legacy fallback.",
    (),
)


def track_policy_engine_failure() -> None:
    policy_engine_failure_total.inc()


def track_policy_circuit_state(state: str) -> None:
    key = (state or "").strip().lower()
    mapping = {"closed": 0.0, "open": 1.0, "half_open": 2.0}
    try:
        policy_engine_circuit_state.set(float(mapping.get(key, -1.0)))
    except (TypeError, ValueError):
        return


def track_safe_fallback() -> None:
    safe_fallback_decisions_total.inc()


def track_policy_engine_wrapped_success() -> None:
    policy_engine_wrapped_success_total.inc()


def track_ai_quality_anomaly() -> None:
    ai_quality_anomaly_total.inc()


def track_decision_route(engine: str) -> None:
    decision_route_counter.labels(engine=engine).inc()


def track_decision_action(engine: str, action: str) -> None:
    action_counter.labels(engine=engine, action=action).inc()


def track_decision_confidence(confidence: float, *, engine: str) -> None:
    try:
        confidence_gauge.labels(engine=engine).set(float(confidence))
    except (TypeError, ValueError):
        return


def track_decision_reward(reward: float, *, engine: str, action: str) -> None:
    try:
        reward_histogram.labels(engine=engine, action=action).observe(float(reward))
    except (TypeError, ValueError):
        return


def track_exploration_bonus(bonus: float) -> None:
    try:
        exploration_gauge.set(float(bonus))
    except (TypeError, ValueError):
        return


def track_bandit_state(actions: Mapping[str, Mapping[str, Any]]) -> None:
    """Mirror per-arm selection counts to a Prometheus Gauge."""

    if not isinstance(actions, Mapping):
        return
    for action, rec in actions.items():
        try:
            count = int((rec or {}).get("count", 0))
        except (TypeError, ValueError):
            continue
        bandit_action_count.labels(action=str(action)).set(count)


# ---------------------------------------------------------------------------
# Latency decorator (sync + async)
# ---------------------------------------------------------------------------


def track_decision_latency(*, engine: str) -> Callable[..., Any]:
    """Decorator measuring wall-clock latency of the wrapped call.

    Works on both synchronous and ``async def`` functions / coroutine methods.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if asyncio.iscoroutinefunction(func) or inspect.isawaitable(func):

            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                start = time.perf_counter()
                try:
                    return await func(*args, **kwargs)
                finally:
                    decision_latency_histogram.labels(engine=engine).observe(
                        time.perf_counter() - start
                    )

            return async_wrapper

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                decision_latency_histogram.labels(engine=engine).observe(
                    time.perf_counter() - start
                )

        return sync_wrapper

    return decorator


# ---------------------------------------------------------------------------
# Outcome feedback loop
# ---------------------------------------------------------------------------


def record_decision_outcome(
    decision: Mapping[str, Any],
    outcome: Mapping[str, Any],
    reward: float,
) -> None:
    """Update Prometheus + propagate outcome to the bandit when applicable.

    The decision dict is the *unified* shape produced by
    :class:`services.decision_router.DecisionRouter` and
    :class:`services.decision_brain_v2.DecisionBrainV2` — both write
    ``engine`` (or ``source``), ``action``, ``intent``, ``domain``,
    ``organization_id``, ``risk_tolerance``, ``time_horizon``,
    ``constraints``, ``metadata``.
    """

    if not isinstance(decision, Mapping):
        return

    engine = str(
        decision.get("engine") or decision.get("source") or "unknown"
    )
    action = str(decision.get("action") or "unknown")

    track_decision_reward(reward, engine=engine, action=action)

    if engine != "policy_engine":
        return

    try:
        from services.policy_engine import (  # local import: avoid cycles
            DecisionContext,
            get_policy_engine,
        )

        decision_context = DecisionContext(
            intent=str(decision.get("intent") or "unknown"),
            domain=str(decision.get("domain") or "system"),
            user_id=decision.get("user_id"),
            organization_id=decision.get("organization_id"),
            risk_tolerance=float(decision.get("risk_tolerance") or 0.5),
            time_horizon=str(decision.get("time_horizon") or "short"),
            constraints=dict(decision.get("constraints") or {}),
            metadata=dict(decision.get("metadata") or {}),
        )
        engine_instance = get_policy_engine()
        engine_instance.update_from_outcome(
            decision_context=decision_context,
            action=action,
            outcome=dict(outcome or {}),
            reward=float(reward),
        )
        track_bandit_state(engine_instance.bandit.actions)
    except Exception as exc:
        logger.warning("record_decision_outcome: bandit update failed: %s", exc)


__all__ = [
    "action_counter",
    "ai_quality_anomaly_total",
    "bandit_action_count",
    "confidence_gauge",
    "decision_latency_histogram",
    "decision_route_counter",
    "exploration_gauge",
    "policy_engine_circuit_state",
    "policy_engine_failure_total",
    "policy_engine_wrapped_success_total",
    "record_decision_outcome",
    "reward_histogram",
    "safe_fallback_decisions_total",
    "track_ai_quality_anomaly",
    "track_bandit_state",
    "track_decision_action",
    "track_decision_confidence",
    "track_decision_latency",
    "track_decision_reward",
    "track_decision_route",
    "track_exploration_bonus",
    "track_policy_circuit_state",
    "track_policy_engine_failure",
    "track_policy_engine_wrapped_success",
    "track_safe_fallback",
]
