"""Unit tests for PolicyEngine circuit breaker wrapper."""

from __future__ import annotations

import pytest

from services.policy_engine_wrapper import (
    CircuitBreakerConfig,
    PolicyEngineCircuitBreaker,
    circuit_runtime_rejected,
)


def test_circuit_opens_after_failures() -> None:
    cb = PolicyEngineCircuitBreaker(
        CircuitBreakerConfig(failure_threshold=3, success_threshold=1, timeout_seconds=300.0)
    )

    def boom() -> None:
        raise ValueError("x")

    for _ in range(2):
        with pytest.raises(ValueError):
            cb.call(boom)
    assert cb.snapshot()["state"] == "closed"

    with pytest.raises(ValueError):
        cb.call(boom)
    assert cb.snapshot()["state"] == "open"

    with pytest.raises(RuntimeError, match="circuit breaker OPEN"):
        cb.call(lambda: 1)


def test_circuit_runtime_rejected() -> None:
    assert circuit_runtime_rejected(RuntimeError("policy circuit breaker OPEN — x")) is True
    assert circuit_runtime_rejected(ValueError("other")) is False
