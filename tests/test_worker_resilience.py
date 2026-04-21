"""Tests for core.worker_resilience and job queue poison / dead-letter policy."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.worker_resilience import (
    CircuitBreaker,
    CircuitState,
    ExponentialBackoff,
    WorkerHealthTracker,
)
from services.job_queue import POISON_MAX_ATTEMPTS, mark_job_failed


def test_circuit_breaker_opens_after_5_failures() -> None:
    cb = CircuitBreaker(fail_threshold=5)
    for _ in range(4):
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
    cb.record_failure()
    assert cb.state == CircuitState.OPEN


def test_circuit_breaker_recovers_after_cooldown() -> None:
    cb = CircuitBreaker(fail_threshold=5, open_seconds=60.0)
    with patch("core.worker_resilience.time.monotonic", return_value=1000.0):
        for _ in range(5):
            cb.record_failure()
    assert cb.state == CircuitState.OPEN
    with patch("core.worker_resilience.time.monotonic", return_value=1061.0):
        assert cb.can_execute() is True
    assert cb.state == CircuitState.HALF_OPEN


def test_circuit_half_open_closes_after_two_successes() -> None:
    cb = CircuitBreaker(fail_threshold=2, open_seconds=10.0, half_open_successes_to_close=2)
    with patch("core.worker_resilience.time.monotonic", return_value=1000.0):
        cb.record_failure()
        cb.record_failure()
    assert cb.state == CircuitState.OPEN
    with patch("core.worker_resilience.time.monotonic", return_value=1011.0):
        assert cb.can_execute() is True
    assert cb.state == CircuitState.HALF_OPEN
    cb.record_success()
    assert cb.state == CircuitState.HALF_OPEN
    cb.record_success()
    assert cb.state == CircuitState.CLOSED


def test_exponential_backoff_increases_delay() -> None:
    bo = ExponentialBackoff(base_delay=1.0, max_delay=300.0, multiplier=2.0, jitter_fraction=0.0)
    d1 = bo.next_sleep()
    d2 = bo.next_sleep()
    assert d1 == 1.0
    assert d2 == 2.0


def test_exponential_backoff_caps_at_max_delay() -> None:
    bo = ExponentialBackoff(base_delay=10.0, max_delay=35.0, multiplier=10.0, jitter_fraction=0.0)
    last = 0.0
    for _ in range(20):
        last = bo.next_sleep()
    assert last == 35.0


def test_poison_job_marked_dead_after_3_failures() -> None:
    assert POISON_MAX_ATTEMPTS == 3
    session = MagicMock()
    job = MagicMock()
    job.id = 42
    job.attempts = 3
    job.max_attempts = 5
    job.started_at = None
    mark_job_failed(session, job, "boom")
    session.execute.assert_called_once()
    stmt = session.execute.call_args[0][0]
    bound = list(stmt._values.values())
    assert any(getattr(p, "value", None) == "dead" for p in bound)


def test_worker_health_tracker_detects_unhealthy() -> None:
    h = WorkerHealthTracker()
    assert h.is_healthy() is True
    base = 1_000_000.0
    # record_failure + failures_in_last_hour / is_healthy each call time.time()
    seq = [base + i * 60.0 for i in range(11)] + [base + 3300.0] * 20
    with patch("core.worker_resilience.time.time", side_effect=seq):
        for _ in range(11):
            h.record_failure("e")
        assert h.failures_in_last_hour() == 11
        assert h.is_healthy() is False
        h.record_success()
    assert h.consecutive_failures == 0
