"""Retryability, backoff, and coordination with stability failure_memory."""

from __future__ import annotations

import math
import time
from typing import Any

from thiramai.config import THIRAMAI_MAX_FIX_RETRIES


# Reviewer / fix path failure types we should not hammer with automatic shell retries.
_NON_RETRYABLE_TYPES = frozenset(
    {
        "approval_denied",
        "invalid_json",
        "unsafe_command",
        "policy_violation",
        "blocked",
    }
)


def is_non_retryable_failure(failure_type: str | None, stderr: str = "") -> bool:
    ft = str(failure_type or "").strip().lower()
    if ft in _NON_RETRYABLE_TYPES:
        return True
    low = (stderr or "").lower()
    if "approval" in low and "denied" in low:
        return True
    return False


def effective_fix_retry_cap(task_cap: int | None = None) -> int:
    """Clamp automated fix retries to configured maximum."""
    cap = int(task_cap) if task_cap is not None else THIRAMAI_MAX_FIX_RETRIES
    return max(0, min(int(cap), THIRAMAI_MAX_FIX_RETRIES))


def backoff_seconds(attempt_index_zero_based: int, *, base: float = 0.8, max_sec: float = 30.0) -> float:
    """Exponential backoff with jitter bounds."""
    i = max(0, int(attempt_index_zero_based))
    raw = base * math.pow(2.0, float(i))
    return float(min(max_sec, raw))


def sleep_backoff(attempt_index_zero_based: int) -> None:
    time.sleep(backoff_seconds(attempt_index_zero_based))


def record_failure_memory_key(module: str, key: str, detail: str = "") -> str:
    """Returns strategy from failure_memory after recording."""
    from core.stability.failure_memory import get_failure_memory

    return get_failure_memory().record(module, key, detail)


def should_skip_retries_from_memory(strategy: str) -> bool:
    return strategy == "skip"
