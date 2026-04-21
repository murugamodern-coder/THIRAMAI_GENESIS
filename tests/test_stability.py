"""Unit tests for core.stability (no ASGI import)."""

from __future__ import annotations

from core.stability.auto_fix_guard import AutoFixGuard
from core.stability.circuit_breaker import CircuitBreaker
from core.stability.failure_memory import FailureMemory
from core.stability.retry import backoff_delay_seconds


def test_backoff_delay_grows_with_jitter() -> None:
    d0 = backoff_delay_seconds(0, base_sec=0.1, max_sec=100.0, jitter_ratio=0.0)
    d3 = backoff_delay_seconds(3, base_sec=0.1, max_sec=100.0, jitter_ratio=0.0)
    assert d3 > d0


def test_circuit_breaker_opens_after_failures() -> None:
    cb = CircuitBreaker(name="test", failure_threshold=3, recovery_timeout_sec=0.05)
    for _ in range(2):
        assert cb.allow_request()
        cb.record_failure()
    assert cb.allow_request()
    cb.record_failure()
    assert not cb.allow_request()


def test_auto_fix_guard_max() -> None:
    g = AutoFixGuard(max_per_issue=2)
    keys = {"a"}
    assert g.can_attempt(keys)
    g.record_attempt(keys)
    assert g.can_attempt(keys)
    g.record_attempt(keys)
    assert not g.can_attempt(keys)


def test_failure_memory_escalates_strategy() -> None:
    fm = FailureMemory()
    fm._repeat_threshold = 2  # type: ignore[attr-defined]
    assert fm.record("m", "k", "e1") == "retry"
    assert fm.record("m", "k", "e2") == "degrade"
    assert fm.record("m", "k", "e3") == "degrade"
    assert fm.record("m", "k", "e4") == "skip"


def test_should_run_priority_critical_always() -> None:
    from core.stability.task_priority import TaskPriority, should_run_priority

    assert should_run_priority(TaskPriority.CRITICAL) is True


def test_circuit_key_stable() -> None:
    from core.stability.circuit_breaker import circuit_key_for_url

    assert "8000" in circuit_key_for_url("http://127.0.0.1:8000")
