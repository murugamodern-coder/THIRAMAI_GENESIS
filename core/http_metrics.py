"""In-process HTTP counters for /health/metrics (Week 1 observability)."""

from __future__ import annotations

from threading import Lock

_lock = Lock()
_requests_total = 0
_errors_total = 0


def record_request(*, status_code: int) -> None:
    global _requests_total, _errors_total
    with _lock:
        _requests_total += 1
        if status_code >= 500:
            _errors_total += 1


def snapshot() -> dict[str, int]:
    with _lock:
        return {"requests_total": _requests_total, "errors_total": _errors_total}
