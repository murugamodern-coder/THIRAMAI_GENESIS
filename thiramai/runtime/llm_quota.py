"""Process-local sliding-window quota for LLM calls (estimated tokens per minute)."""

from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.Lock()
_window_sec = 60.0
_events: list[tuple[float, int]] = []


def _prune(now: float) -> None:
    cutoff = now - _window_sec
    global _events
    _events = [e for e in _events if e[0] >= cutoff]


def allow_or_raise(estimated_tokens: int, *, limit_per_minute: int) -> None:
    """
    Raises RuntimeError if quota exceeded.
    When *limit_per_minute* <= 0, quota is disabled.
    """
    if limit_per_minute <= 0:
        return
    est = max(1, int(estimated_tokens))
    now = time.monotonic()
    with _lock:
        _prune(now)
        used = sum(t for _, t in _events)
        if used + est > limit_per_minute:
            raise RuntimeError(
                f"THIRAMAI LLM token quota exceeded ({used}+{est} > {limit_per_minute} est. tokens / minute)."
            )
        _events.append((now, est))


def record_actual(estimated_tokens: int) -> None:
    """Track usage after successful call (already counted in allow_or_raise — noop unless used separately)."""
    del estimated_tokens


def snapshot() -> dict[str, Any]:
    now = time.monotonic()
    with _lock:
        _prune(now)
        used = sum(t for _, t in _events)
        return {"estimated_tokens_last_minute": used, "events": len(_events)}
