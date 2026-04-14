"""Per-user LLM usage caps (Redis) to limit abuse and cost."""

from __future__ import annotations

import logging
import os
from datetime import date

_log = logging.getLogger("thiramai.ai_usage")


def _per_minute() -> int:
    try:
        return max(1, min(int((os.getenv("THIRAMAI_RL_LLM_USER_PER_MINUTE") or "30").strip()), 600))
    except ValueError:
        return 30


def _per_day() -> int:
    try:
        return max(10, min(int((os.getenv("THIRAMAI_RL_LLM_USER_PER_DAY") or "800").strip()), 50_000))
    except ValueError:
        return 800


def consume_llm_units(user_id: int, *, units: int = 1) -> tuple[bool, str | None]:
    """
    Increment usage counters. Returns (allowed, error_detail).

    When ``REDIS_URL`` is unset, allows all traffic (same as other distributed limits).
    """
    uid = int(user_id)
    if uid <= 0:
        return False, "invalid user"
    try:
        from services.worker_heartbeat import redis_client

        r = redis_client()
        if r is None:
            return True, None
    except Exception as exc:
        _log.debug("ai_usage redis: %s", exc)
        return True, None

    day = date.today().isoformat()
    k_day = f"thiramai:llm:day:{uid}:{day}"
    k_min = f"thiramai:llm:min:{uid}"
    try:
        pipe = r.pipeline()
        pipe.incr(k_day, int(units))
        pipe.expire(k_day, 86400 * 2)
        pipe.incr(k_min, int(units))
        pipe.expire(k_min, 120)
        dcount, _, mcount, _ = pipe.execute()
        if int(dcount or 0) > _per_day():
            r.decr(k_day, int(units))
            r.decr(k_min, int(units))
            return False, "daily LLM budget exceeded"
        if int(mcount or 0) > _per_minute():
            r.decr(k_day, int(units))
            r.decr(k_min, int(units))
            return False, "LLM rate limit exceeded (per minute)"
        return True, None
    except Exception as exc:
        _log.warning("ai_usage increment failed: %s", exc)
        return True, None
