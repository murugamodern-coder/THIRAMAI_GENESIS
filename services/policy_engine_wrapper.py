"""
PolicyEngine resilience: circuit breaker around :meth:`PolicyEngine.decide` plus a
deterministic **safe_fallback** V2 payload when the engine is unavailable.

Callers use :func:`guarded_policy_decide` and :func:`build_safe_fallback_v2_payload`.
This module uses the **process-global** :func:`services.policy_engine.get_policy_engine`
singleton; it does not construct a second PolicyEngine.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, TypeVar

from services.policy_engine import DecisionContext, PolicyEngine

_LOG = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True)
class CircuitBreakerConfig:
    failure_threshold: int
    success_threshold: int
    timeout_seconds: float


def _int_env(*names: str, default: int) -> int:
    for name in names:
        raw = (os.getenv(name) or "").strip()
        if raw:
            try:
                return int(raw, 10)
            except ValueError:
                continue
    return default


def _float_env_cb(*names: str, default: float) -> float:
    for name in names:
        raw = (os.getenv(name) or "").strip()
        if raw:
            try:
                return float(raw)
            except ValueError:
                continue
    return default


def load_circuit_config() -> CircuitBreakerConfig:
    return CircuitBreakerConfig(
        failure_threshold=max(
            1,
            _int_env(
                "THIRAMAI_POLICY_CB_FAILURE_THRESHOLD",
                "CIRCUIT_BREAKER_FAILURE_THRESHOLD",
                default=5,
            ),
        ),
        success_threshold=max(
            1,
            _int_env(
                "THIRAMAI_POLICY_CB_SUCCESS_THRESHOLD",
                "CIRCUIT_BREAKER_SUCCESS_THRESHOLD",
                default=2,
            ),
        ),
        timeout_seconds=max(
            1.0,
            _float_env_cb(
                "THIRAMAI_POLICY_CB_TIMEOUT_SECONDS",
                "CIRCUIT_BREAKER_TIMEOUT_SECONDS",
                default=60.0,
            ),
        ),
    )


class PolicyEngineCircuitBreaker:
    """Thread-safe circuit breaker for synchronous ``PolicyEngine.decide`` calls."""

    def __init__(self, config: CircuitBreakerConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: datetime | None = None
        self._last_state_change = datetime.now(timezone.utc)
        self._emit_circuit_metric()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self._state.value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "last_failure_time": self._last_failure_time.isoformat()
                if self._last_failure_time
                else None,
                "last_state_change": self._last_state_change.isoformat(),
                "failure_threshold": self._config.failure_threshold,
                "success_threshold": self._config.success_threshold,
                "timeout_seconds": self._config.timeout_seconds,
            }

    def call(self, fn: Callable[[], T]) -> T:
        with self._lock:
            if self._state == CircuitState.OPEN:
                if self._should_attempt_reset_unlocked():
                    _LOG.info("policy circuit: half-open (retry window)")
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0
                    self._last_state_change = datetime.now(timezone.utc)
                    self._emit_circuit_metric()
                else:
                    self._emit_circuit_metric()
                    raise RuntimeError(
                        "policy circuit breaker OPEN — PolicyEngine short-circuit; "
                        f"retry after {self._config.timeout_seconds:.0f}s"
                    )
            elif self._state == CircuitState.HALF_OPEN:
                pass

        try:
            result = fn()
        except Exception:
            with self._lock:
                self._record_failure_unlocked()
            raise

        with self._lock:
            self._record_success_unlocked()
        return result

    def _should_attempt_reset_unlocked(self) -> bool:
        if self._last_failure_time is None:
            return True
        elapsed = (datetime.now(timezone.utc) - self._last_failure_time).total_seconds()
        return elapsed >= self._config.timeout_seconds

    def _record_success_unlocked(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self._config.success_threshold:
                _LOG.info("policy circuit: CLOSED after recovery successes")
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._success_count = 0
                self._last_state_change = datetime.now(timezone.utc)
        elif self._state == CircuitState.CLOSED and self._failure_count > 0:
            self._failure_count = 0
        self._emit_circuit_metric()

    def _record_failure_unlocked(self) -> None:
        self._failure_count += 1
        self._last_failure_time = datetime.now(timezone.utc)

        if self._state == CircuitState.HALF_OPEN:
            _LOG.warning("policy circuit: OPEN (failed during half-open)")
            self._state = CircuitState.OPEN
            self._last_state_change = datetime.now(timezone.utc)
        elif (
            self._state == CircuitState.CLOSED
            and self._failure_count >= self._config.failure_threshold
        ):
            _LOG.error(
                "policy circuit: OPEN after %s failures (timeout=%ss)",
                self._failure_count,
                self._config.timeout_seconds,
            )
            self._state = CircuitState.OPEN
            self._last_state_change = datetime.now(timezone.utc)
        self._emit_circuit_metric()

    def _emit_circuit_metric(self) -> None:
        try:
            from services.observability.decision_metrics import track_policy_circuit_state

            track_policy_circuit_state(self._state.value)
        except Exception:
            pass


_cb_singleton: PolicyEngineCircuitBreaker | None = None
_cb_lock = threading.Lock()


def get_policy_circuit_breaker() -> PolicyEngineCircuitBreaker:
    global _cb_singleton
    with _cb_lock:
        if _cb_singleton is None:
            _cb_singleton = PolicyEngineCircuitBreaker(load_circuit_config())
        return _cb_singleton


def reset_policy_circuit_breaker_for_tests() -> None:
    """Test helper: drop breaker state."""
    global _cb_singleton
    with _cb_lock:
        _cb_singleton = None


def guarded_policy_decide(engine: PolicyEngine, context: DecisionContext) -> Any:
    """Run ``engine.decide(context)`` behind the process circuit breaker."""
    cb = get_policy_circuit_breaker()

    def _fn() -> Any:
        return engine.decide(context)

    return cb.call(_fn)


def build_safe_fallback_v2_payload(
    *,
    reason: str,
    intent: str,
    domain: str,
    user_id: int | None,
    organization_id: int | None,
    decision_context: DecisionContext,
    policy_engine: PolicyEngine,
) -> dict[str, Any]:
    """
    Unified V2 dict (same shape as a successful policy run) with ``source=safe_fallback``.

    Uses policy arm ``no_action`` so :func:`api.routes.ai_chat._bundle_from_decision_brain_v2`
    can map to executor ``noop``.
    """
    ts = datetime.now(timezone.utc)
    msg = (reason or "").strip() or "policy_unavailable"
    reasoning = [
        "Degraded mode: PolicyEngine unavailable. Conservative no-action (safe fallback).",
        f"detail: {msg[:500]}",
    ]
    action = "no_action"
    return {
        "action": action,
        "action_type": policy_engine._classify_action(action),  # noqa: SLF001
        "confidence": 0.3,
        "reasoning": reasoning,
        "expected_reward": 0.0,
        "exploration_bonus": 0.0,
        "source": "safe_fallback",
        "timestamp": ts.isoformat(),
        "learning_log_id": None,
        "intent": intent,
        "domain": domain,
        "user_id": user_id,
        "organization_id": organization_id,
        "risk_tolerance": decision_context.risk_tolerance,
        "time_horizon": decision_context.time_horizon,
        "constraints": decision_context.constraints,
        "metadata": dict(decision_context.metadata or {}),
        "fallback_reason": msg[:800],
        "circuit_snapshot": get_policy_circuit_breaker().snapshot(),
    }


def circuit_runtime_rejected(exc: BaseException) -> bool:
    """True if ``exc`` is the breaker short-circuit (no call to PolicyEngine)."""
    return isinstance(exc, RuntimeError) and "circuit breaker OPEN" in str(exc)


__all__ = [
    "CircuitBreakerConfig",
    "CircuitState",
    "build_safe_fallback_v2_payload",
    "circuit_runtime_rejected",
    "get_policy_circuit_breaker",
    "guarded_policy_decide",
    "load_circuit_config",
    "reset_policy_circuit_breaker_for_tests",
]
