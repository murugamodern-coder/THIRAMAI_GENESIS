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


def _per_day_paid() -> int:
    try:
        return max(10, min(int((os.getenv("THIRAMAI_RL_LLM_USER_PER_DAY") or "800").strip()), 50_000))
    except ValueError:
        return 800


def _per_day_free() -> int:
    try:
        return max(5, min(int((os.getenv("THIRAMAI_RL_LLM_USER_PER_DAY_FREE") or "45").strip()), 500))
    except ValueError:
        return 45


def _per_day_limit_for_plan(plan: str | None) -> int:
    p = (plan or "free").strip().lower()
    if p in ("business", "enterprise"):
        return min(50_000, _per_day_paid() * 8)
    if p == "pro":
        return min(50_000, max(_per_day_paid(), 2500))
    return _per_day_free()


def consume_llm_units(user_id: int, *, units: int = 1, plan: str | None = None) -> tuple[bool, str | None]:
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
        day_limit = _per_day_limit_for_plan(plan)
        if int(dcount or 0) > day_limit:
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
