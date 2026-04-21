"""
Incremental migrations for ``goal_jobs.sqlite`` (phase 55).

Application ships ``GOAL_SQLITE_SCHEMA_VERSION``; DB stores current applied version in ``schema_meta``.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any

logger = logging.getLogger("thiramai.goal_sqlite")

GOAL_SQLITE_SCHEMA_VERSION = 3
_META_KEY = "goal_jobs_sqlite_schema"


def apply_goal_jobs_migrations(cx: sqlite3.Connection) -> dict[str, Any]:
    """
    Apply pending migrations in order. Safe to call on every ``ensure_schema()`` — fast no-op when current.

    If the database reports a **newer** schema than this binary understands, logs an error.
    Set ``THIRAMAI_SQLITE_SCHEMA_STRICT=1`` to raise ``RuntimeError`` (fail-fast).
    """
    cx.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_meta (
          k TEXT PRIMARY KEY,
          v TEXT NOT NULL
        )
        """
    )
    row = cx.execute("SELECT v FROM schema_meta WHERE k = ?", (_META_KEY,)).fetchone()
    db_ver = int(row["v"]) if row else 1

    target = GOAL_SQLITE_SCHEMA_VERSION
    if db_ver > target:
        msg = (
            f"goal_jobs.sqlite schema version {db_ver} is newer than application {target} "
            "(downgrade binary or restore backup)"
        )
        logger.error(msg)
        if (os.getenv("THIRAMAI_SQLITE_SCHEMA_STRICT") or "").strip() in ("1", "true", "yes", "on"):
            raise RuntimeError(msg)
        return {"previous": db_ver, "target": target, "applied": [], "db_newer_than_app": True}

    applied: list[str] = []
    v = db_ver
    while v < target:
        next_v = v + 1
        _migrate_to_version(cx, next_v)
        cx.execute(
            "INSERT INTO schema_meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
            (_META_KEY, str(next_v)),
        )
        applied.append(f"v{next_v}")
        v = next_v

    return {"previous": db_ver, "target": target, "applied": applied}


def _migrate_to_version(cx: sqlite3.Connection, version: int) -> None:
    if version == 2:
        cx.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_jobs_org_dispatch_status
            ON jobs (organization_id, dispatch_mode, status)
            """
        )
        try:
            cx.execute("ALTER TABLE worker_heartbeats ADD COLUMN release_version TEXT")
        except sqlite3.OperationalError:
            pass
    elif version == 3:
        try:
            cx.execute("ALTER TABLE jobs ADD COLUMN replay_source_job_id TEXT")
        except sqlite3.OperationalError:
            pass
