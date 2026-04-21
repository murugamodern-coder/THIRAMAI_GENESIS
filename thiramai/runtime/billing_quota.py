"""Per-tenant usage counters and soft quotas (SQLite, UTC day buckets)."""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timezone

from thiramai.config import (
    DATA_DIR,
    THIRAMAI_DAILY_GOAL_JOBS_PER_USER,
    THIRAMAI_DAILY_TOKEN_BUDGET_PER_USER,
)

_lock = threading.Lock()


def _day_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    from thiramai.runtime.sqlite_job_store import ensure_schema

    ensure_schema()
    p = DATA_DIR / "goal_jobs.sqlite"
    c = sqlite3.connect(str(p), check_same_thread=False, timeout=30.0)
    return c


def record_job_submitted(organization_id: int, user_id: int) -> None:
    oid, uid = int(organization_id), int(user_id)
    day = _day_key()
    with _lock:
        with _connect() as cx:
            cx.execute(
                """
                INSERT INTO goal_usage_daily (organization_id, user_id, day_yyyymmdd, jobs_submitted)
                VALUES (?,?,?,1)
                ON CONFLICT(organization_id, user_id, day_yyyymmdd) DO UPDATE SET
                  jobs_submitted = jobs_submitted + 1
                """,
                (oid, uid, day),
            )
            cx.commit()


def record_api_call(organization_id: int, user_id: int) -> None:
    oid, uid = int(organization_id), int(user_id)
    day = _day_key()
    with _lock:
        with _connect() as cx:
            cx.execute(
                """
                INSERT INTO goal_usage_daily (organization_id, user_id, day_yyyymmdd, api_calls)
                VALUES (?,?,?,1)
                ON CONFLICT(organization_id, user_id, day_yyyymmdd) DO UPDATE SET
                  api_calls = api_calls + 1
                """,
                (oid, uid, day),
            )
            cx.commit()


def record_tokens_estimated(organization_id: int, user_id: int, n: int) -> None:
    if n <= 0:
        return
    oid, uid = int(organization_id), int(user_id)
    day = _day_key()
    with _lock:
        with _connect() as cx:
            cx.execute(
                """
                INSERT INTO goal_usage_daily (organization_id, user_id, day_yyyymmdd, tokens_estimated)
                VALUES (?,?,?,?)
                ON CONFLICT(organization_id, user_id, day_yyyymmdd) DO UPDATE SET
                  tokens_estimated = tokens_estimated + ?
                """,
                (oid, uid, day, int(n), int(n)),
            )
            cx.commit()


def _row_for_day(organization_id: int, user_id: int) -> tuple[int, int, int]:
    oid, uid = int(organization_id), int(user_id)
    day = _day_key()
    with _connect() as cx:
        row = cx.execute(
            "SELECT jobs_submitted, tokens_estimated, api_calls FROM goal_usage_daily "
            "WHERE organization_id = ? AND user_id = ? AND day_yyyymmdd = ?",
            (oid, uid, day),
        ).fetchone()
        if not row:
            return 0, 0, 0
        return int(row[0]), int(row[1]), int(row[2])


def assert_goal_submit_allowed(organization_id: int, user_id: int) -> None:
    """Raise ValueError with quota message when daily caps exceeded."""
    cap_jobs = int(THIRAMAI_DAILY_GOAL_JOBS_PER_USER or 0)
    cap_tok = int(THIRAMAI_DAILY_TOKEN_BUDGET_PER_USER or 0)
    jobs, tokens, _api = _row_for_day(organization_id, user_id)
    if cap_jobs > 0 and jobs >= cap_jobs:
        raise ValueError(f"daily goal job quota exceeded ({cap_jobs} jobs per user per day)")
    if cap_tok > 0 and tokens >= cap_tok:
        raise ValueError(f"daily token budget exceeded ({cap_tok} estimated tokens per user per day)")


def assert_llm_allowed(organization_id: int, user_id: int, estimated_next: int = 0) -> None:
    cap_tok = int(THIRAMAI_DAILY_TOKEN_BUDGET_PER_USER or 0)
    if cap_tok <= 0:
        return
    _jobs, tokens, _a = _row_for_day(organization_id, user_id)
    if tokens + max(0, int(estimated_next)) > cap_tok:
        raise RuntimeError(
            f"daily token budget would be exceeded ({cap_tok} estimated tokens per user per day)"
        )
