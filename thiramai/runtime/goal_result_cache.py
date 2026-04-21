"""In-memory goal → completed job snapshot cache with TTL (lightweight)."""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any

from thiramai.config import (
    THIRAMAI_GOAL_CACHE_DATA_VERSION,
    THIRAMAI_GOAL_CACHE_ENABLED,
    THIRAMAI_GOAL_CACHE_TTL_SEC,
)

_lock = threading.Lock()
_entries: dict[str, tuple[float, str]] = {}


def _key(organization_id: int, user_id: int, goal: str) -> str:
    raw = f"{organization_id}:{user_id}:{THIRAMAI_GOAL_CACHE_DATA_VERSION}:{goal.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_cached_job_id(organization_id: int, user_id: int, goal: str) -> str | None:
    if not THIRAMAI_GOAL_CACHE_ENABLED:
        return None
    k = _key(organization_id, user_id, goal)
    now = time.time()
    with _lock:
        ent = _entries.get(k)
        if not ent:
            return None
        ts, jid = ent
        if now - ts > THIRAMAI_GOAL_CACHE_TTL_SEC:
            del _entries[k]
            return None
        return jid


def remember(organization_id: int, user_id: int, goal: str, job_id: str) -> None:
    if not THIRAMAI_GOAL_CACHE_ENABLED:
        return
    k = _key(organization_id, user_id, goal)
    with _lock:
        _entries[k] = (time.time(), job_id)
        # bound size (best-effort)
        if len(_entries) > 2000:
            cutoff = time.time() - THIRAMAI_GOAL_CACHE_TTL_SEC
            stale = [kk for kk, (ts, _) in _entries.items() if ts < cutoff]
            for kk in stale[:500]:
                _entries.pop(kk, None)


def reset_for_tests() -> None:
    with _lock:
        _entries.clear()
