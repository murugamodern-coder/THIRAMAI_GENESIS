"""
Redis-backed get-or-set cache with in-process fallback (single-instance / dev).

Keys are prefixed ``thiramai:appcache:`` to avoid collisions with heartbeats and stock quotes.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

from cache.keys import build_stable_key, key_research_market, key_today_brief

_log = logging.getLogger("thiramai.cache")

_T = TypeVar("_T")

_MEM: dict[str, tuple[float, str]] = {}
_MEM_LOCK = threading.Lock()


def get_or_set_cache(key: str, ttl_sec: int, compute_fn: Callable[[], _T]) -> _T:
    """
    Return cached JSON-deserializable value or run ``compute_fn`` once.

    ``ttl_sec`` clamped to 1..86400. When Redis is unavailable, uses bounded in-memory LRU-ish map.
    """
    ttl = max(1, min(int(ttl_sec), 86400))
    now = time.monotonic()
    try:
        from services.worker_heartbeat import redis_client

        r = redis_client()
        if r:
            raw = r.get(key)
            if raw:
                try:
                    return json.loads(raw)  # type: ignore[no-any-return]
                except Exception:
                    _log.debug("cache corrupt key=%s", key[:80])
            val = compute_fn()
            try:
                blob = json.dumps(val, default=str)
                r.setex(key, ttl, blob)
            except Exception as exc:
                _log.debug("cache set failed: %s", exc)
            return val
    except Exception as exc:
        _log.debug("cache redis path: %s", exc)

    with _MEM_LOCK:
        hit = _MEM.get(key)
        if hit and now - hit[0] < float(ttl):
            try:
                return json.loads(hit[1])  # type: ignore[no-any-return]
            except Exception:
                pass
        val = compute_fn()
        try:
            _MEM[key] = (now, json.dumps(val, default=str))
        except Exception:
            pass
        if len(_MEM) > 2000:
            cutoff = now - 1.0
            for k in list(_MEM.keys())[:500]:
                if _MEM.get(k, (0,))[0] < cutoff:
                    _MEM.pop(k, None)
        return val


def cache_key_today_brief(user_id: int, organization_id: int, day_iso: str) -> str:
    return key_today_brief(user_id, organization_id, day_iso)


def cache_key_research_market(user_id: int, organization_id: int, query: str) -> str:
    return key_research_market(user_id, organization_id, query)


# Back-compat for callers that built ad-hoc keys
def cache_key_stable(*parts: str) -> str:
    return build_stable_key(*parts)
