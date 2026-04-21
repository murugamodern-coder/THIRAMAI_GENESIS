"""
Production-grade worker utilities: circuit breaker, exponential backoff, health tracking.

Used by ``workers.run_worker`` and ``workers.alert_system`` to avoid hammering a broken DB,
thundering herds on retry, and silent failure modes.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from enum import Enum


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """
    Three states: CLOSED (normal), OPEN (failing, reject calls), HALF_OPEN (testing recovery).

    - Opens after 5 consecutive failures
    - Tries recovery after 60 seconds (OPEN → HALF_OPEN allows one probe path via can_execute)
    - Closes after 2 consecutive successes while HALF_OPEN
    """

    def __init__(
        self,
        *,
        fail_threshold: int = 5,
        open_seconds: float = 60.0,
        half_open_successes_to_close: int = 2,
    ) -> None:
        self._fail_threshold = max(1, fail_threshold)
        self._open_seconds = open_seconds
        self._half_open_successes_to_close = max(1, half_open_successes_to_close)
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._half_open_successes = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> CircuitState:
        return self._state

    def can_execute(self) -> bool:
        """Return True if the guarded operation may run now."""
        now = time.monotonic()
        if self._state == CircuitState.OPEN:
            if self._opened_at is not None and now >= self._opened_at + self._open_seconds:
                self._state = CircuitState.HALF_OPEN
                self._half_open_successes = 0
                return True
            return False
        return True

    def seconds_until_half_open(self) -> float:
        """When OPEN, seconds until HALF_OPEN probe is allowed; 0 if not OPEN."""
        if self._state != CircuitState.OPEN or self._opened_at is None:
            return 0.0
        return max(0.0, self._opened_at + self._open_seconds - time.monotonic())

    def record_success(self) -> None:
        """Call after a successful guarded operation (including healthy idle / no-op)."""
        if self._state == CircuitState.HALF_OPEN:
            self._half_open_successes += 1
            if self._half_open_successes >= self._half_open_successes_to_close:
                self._state = CircuitState.CLOSED
                self._consecutive_failures = 0
                self._half_open_successes = 0
                self._opened_at = None
        elif self._state == CircuitState.CLOSED:
            self._consecutive_failures = 0

    def record_failure(self) -> None:
        """Call after a guarded operation fails (e.g. DB error)."""
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()
            self._half_open_successes = 0
            self._consecutive_failures += 1
            return
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._fail_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()

    def reset(self) -> None:
        """Manual reset (tests / admin)."""
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._half_open_successes = 0
        self._opened_at = None


class ExponentialBackoff:
    """
    - base_delay: 1 second
    - max_delay: 300 seconds (5 minutes) by default; alert worker may use a lower cap
    - multiplier: 2x per failure
    - jitter: random 0–10% of raw delay to reduce thundering herd
    - resets on success
    """

    def __init__(
        self,
        *,
        base_delay: float = 1.0,
        max_delay: float = 300.0,
        multiplier: float = 2.0,
        jitter_fraction: float = 0.10,
    ) -> None:
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.multiplier = multiplier
        self.jitter_fraction = min(0.5, max(0.0, jitter_fraction))
        self._failure_streak = 0

    @property
    def failure_streak(self) -> int:
        return self._failure_streak

    def reset(self) -> None:
        self._failure_streak = 0

    def next_sleep(self) -> float:
        """
        Increment failure streak and return delay to sleep before retrying (with jitter).
        Call after a failure when you will sleep before the next attempt.
        """
        self._failure_streak += 1
        raw = min(
            self.base_delay * (self.multiplier ** max(0, self._failure_streak - 1)),
            self.max_delay,
        )
        jitter = random.uniform(0.0, self.jitter_fraction * raw) if raw > 0 else 0.0
        return raw + jitter

    def peek_delay_without_increment(self) -> float:
        """Preview delay for current streak without incrementing (e.g. logging)."""
        raw = min(
            self.base_delay * (self.multiplier ** max(0, self._failure_streak)),
            self.max_delay,
        )
        jitter = random.uniform(0.0, self.jitter_fraction * raw) if raw > 0 else 0.0
        return raw + jitter


@dataclass
class WorkerHealthTracker:
    """
    Tracks consecutive_failures, total_failures, last_error, last_success_at.
    ``is_healthy()`` is False if more than 10 failure events occurred in the last hour.
    """

    consecutive_failures: int = 0
    total_failures: int = 0
    total_successes: int = 0
    last_error: str | None = None
    last_success_at: float | None = None
    _failure_timestamps: list[float] = field(default_factory=list)

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.total_successes += 1
        self.last_success_at = time.time()

    def record_failure(self, message: str) -> None:
        self.consecutive_failures += 1
        self.total_failures += 1
        self.last_error = (message or "")[:2000]
        now = time.time()
        self._failure_timestamps.append(now)
        cutoff = now - 3600.0
        self._failure_timestamps = [t for t in self._failure_timestamps if t > cutoff]

    def failures_in_last_hour(self) -> int:
        now = time.time()
        cutoff = now - 3600.0
        self._failure_timestamps = [t for t in self._failure_timestamps if t > cutoff]
        return len(self._failure_timestamps)

    def is_healthy(self) -> bool:
        return self.failures_in_last_hour() <= 10

    def reset(self) -> None:
        self.consecutive_failures = 0
        self.total_failures = 0
        self.total_successes = 0
        self.last_error = None
        self.last_success_at = None
        self._failure_timestamps.clear()
