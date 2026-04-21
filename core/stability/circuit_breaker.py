"""Circuit breaker for external calls (HTTP, integrations). Lightweight, process-local."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from core.stability.logging_tags import log_circuit


class _State(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """
    After *failure_threshold* consecutive failures, opens for *recovery_timeout_sec*.
    One successful call in half-open closes the circuit.
    """

    name: str
    failure_threshold: int = 5
    recovery_timeout_sec: float = 60.0
    _state: _State = field(default=_State.CLOSED, init=False)
    _failures: int = field(default=0, init=False)
    _opened_at: float = field(default=0.0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def allow_request(self) -> bool:
        with self._lock:
            if self._state == _State.OPEN:
                if time.monotonic() - self._opened_at >= self.recovery_timeout_sec:
                    self._state = _State.HALF_OPEN
                    log_circuit(f"{self.name}: half-open (cooldown elapsed)")
                    return True
                return False
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            if self._state != _State.CLOSED:
                log_circuit(f"{self.name}: closed after success")
            self._state = _State.CLOSED

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._state == _State.HALF_OPEN:
                self._state = _State.OPEN
                self._opened_at = time.monotonic()
                log_circuit(f"{self.name}: open (half-open failure)")
                return
            if self._failures >= self.failure_threshold:
                if self._state != _State.OPEN:
                    self._state = _State.OPEN
                    self._opened_at = time.monotonic()
                    log_circuit(
                        f"{self.name}: open after {self._failures} consecutive failures "
                        f"(retry after {self.recovery_timeout_sec:.1f}s)"
                    )

    def reset(self) -> None:
        with self._lock:
            self._state = _State.CLOSED
            self._failures = 0
            self._opened_at = 0.0

    def public_snapshot(self) -> dict[str, object]:
        """JSON-serializable state for observability (no sensitive data)."""
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.value,
                "failures_consecutive": self._failures,
                "failure_threshold": self.failure_threshold,
                "recovery_timeout_sec": self.recovery_timeout_sec,
            }


_registry: dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_circuit_breaker(name: str) -> CircuitBreaker:
    """Named singleton per process."""
    with _registry_lock:
        if name not in _registry:
            ft = int(os.environ.get("THIRAMAI_STABILITY_CB_FAILURE_THRESHOLD", "5") or "5")
            cool = float(os.environ.get("THIRAMAI_STABILITY_CB_COOLDOWN_SEC", "60") or "60")
            _registry[name] = CircuitBreaker(
                name=name,
                failure_threshold=max(1, ft),
                recovery_timeout_sec=max(1.0, cool),
            )
        return _registry[name]


def circuit_key_for_url(base_url: str) -> str:
    """Stable key from API base (e.g. http://127.0.0.1:8000)."""
    return base_url.rstrip("/").replace("://", "_").replace(":", "_").replace("/", "_")


def export_breaker_snapshots() -> list[dict[str, object]]:
    """All circuit breakers registered in-process (for /ai/internal/metrics)."""
    with _registry_lock:
        return [cb.public_snapshot() for cb in _registry.values()]
