"""
SQLite persistence for autonomous goal jobs (restart-safe).

WAL mode, thread-local connections via ``connect()`` per operation with ``check_same_thread=False``.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from thiramai.config import DATA_DIR, THIRAMAI_GOAL_FAIR_QUEUE_RR


def _db_path() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / "goal_jobs.sqlite"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


_store_lock = threading.Lock()
_initialized = False


def ensure_schema() -> None:
    """Create tables once per process; run SQLite migrations every call (cheap version check)."""
    global _initialized
    from thiramai.runtime.goal_sqlite_migrations import apply_goal_jobs_migrations

    with _store_lock:
        with _connect() as cx:
            cx.execute("PRAGMA journal_mode=WAL")
            cx.execute("PRAGMA synchronous=NORMAL")
            cx.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY,
                  goal TEXT NOT NULL,
                  status TEXT NOT NULL,
                  created_ts REAL NOT NULL,
                  started_ts REAL,
                  finished_ts REAL,
                  deadline_ts REAL,
                  ok INTEGER,
                  clean_cycle INTEGER,
                  deadline_hit INTEGER,
                  error TEXT,
                  progress_pct REAL DEFAULT 0,
                  max_seconds INTEGER,
                  fixed_goal_only INTEGER DEFAULT 1,
                  latest_results_json TEXT,
                  failures_json TEXT,
                  task_states_json TEXT,
                  worker_claim TEXT,
                  execution_ms REAL,
                  dispatch_mode TEXT DEFAULT 'inline'
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
                CREATE TABLE IF NOT EXISTS task_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  job_id TEXT NOT NULL,
                  step_key TEXT NOT NULL,
                  state TEXT NOT NULL,
                  ts REAL NOT NULL,
                  detail_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_task_events_job ON task_events(job_id);
                CREATE TABLE IF NOT EXISTS connector_audit (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  ts REAL NOT NULL,
                  action_type TEXT NOT NULL,
                  ok INTEGER NOT NULL,
                  detail_json TEXT NOT NULL
                );
                """
            )
            for stmt in (
                "ALTER TABLE jobs ADD COLUMN dispatch_mode TEXT DEFAULT 'inline'",
                "ALTER TABLE jobs ADD COLUMN execution_ms REAL",
                "ALTER TABLE jobs ADD COLUMN task_states_json TEXT",
                "ALTER TABLE jobs ADD COLUMN worker_claim TEXT",
                "ALTER TABLE jobs ADD COLUMN failure_analysis_json TEXT",
                "ALTER TABLE jobs ADD COLUMN user_id INTEGER DEFAULT 0",
                "ALTER TABLE jobs ADD COLUMN organization_id INTEGER DEFAULT 0",
                "ALTER TABLE jobs ADD COLUMN idempotency_key TEXT",
                "ALTER TABLE jobs ADD COLUMN version_id TEXT",
                "ALTER TABLE jobs ADD COLUMN slow_job INTEGER DEFAULT 0",
                "ALTER TABLE jobs ADD COLUMN replay_source_job_id TEXT",
            ):
                try:
                    cx.execute(stmt)
                except sqlite3.OperationalError:
                    pass
            try:
                cx.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS ux_jobs_idempotency
                    ON jobs(organization_id, user_id, idempotency_key)
                    WHERE idempotency_key IS NOT NULL AND length(trim(idempotency_key)) > 0
                    """
                )
            except sqlite3.OperationalError:
                pass
            cx.executescript(
                """
                CREATE TABLE IF NOT EXISTS worker_heartbeats (
                  worker_id TEXT PRIMARY KEY,
                  ts REAL NOT NULL,
                  status TEXT NOT NULL,
                  current_job_id TEXT,
                  organization_id INTEGER DEFAULT 0
                );
                """
            )
            try:
                cx.execute("ALTER TABLE worker_heartbeats ADD COLUMN organization_id INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            cx.executescript(
                """
                CREATE TABLE IF NOT EXISTS fair_queue_rr (
                  id INTEGER PRIMARY KEY CHECK (id = 1),
                  last_organization_id INTEGER
                );
                INSERT OR IGNORE INTO fair_queue_rr (id, last_organization_id) VALUES (1, NULL);
                """
            )
            cx.execute(
                """
                CREATE TABLE IF NOT EXISTS goal_usage_daily (
                  organization_id INTEGER NOT NULL,
                  user_id INTEGER NOT NULL,
                  day_yyyymmdd TEXT NOT NULL,
                  jobs_submitted INTEGER NOT NULL DEFAULT 0,
                  tokens_estimated INTEGER NOT NULL DEFAULT 0,
                  api_calls INTEGER NOT NULL DEFAULT 0,
                  PRIMARY KEY (organization_id, user_id, day_yyyymmdd)
                )
                """
            )
            apply_goal_jobs_migrations(cx)
            _initialized = True


def jobs_database_path() -> Path:
    """Path to goal jobs SQLite (shared with usage counters)."""
    return _db_path()


def job_id_for_idempotency_key(organization_id: int, user_id: int, key: str) -> str | None:
    """Return existing job id when the same tenant resubmits with the same idempotency key."""
    k = (key or "").strip()
    if not k:
        return None
    ensure_schema()
    with _connect() as cx:
        row = cx.execute(
            "SELECT id FROM jobs WHERE organization_id = ? AND user_id = ? AND idempotency_key = ? LIMIT 1",
            (int(organization_id), int(user_id), k[:512]),
        ).fetchone()
        return str(row["id"]) if row else None


def sqlite_goal_queue_depth() -> dict[str, int]:
    """Counts by status for worker-dispatched queue visibility."""
    ensure_schema()
    with _connect() as cx:
        rows = cx.execute(
            "SELECT status, COUNT(*) AS c FROM jobs WHERE dispatch_mode = 'worker' GROUP BY status"
        ).fetchall()
    out: dict[str, int] = {}
    for r in rows:
        out[str(r["status"])] = int(r["c"])
    return out


def sqlite_jobs_ping_ok() -> tuple[bool, str]:
    """Lightweight read for readiness."""
    try:
        ensure_schema()
        with _connect() as cx:
            cx.execute("SELECT COUNT(*) FROM jobs LIMIT 1").fetchone()
        return True, "sqlite readable"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def recover_after_restart(mark_interrupted: bool, resume_as_queued: bool) -> list[str]:
    """
    On server boot: optionally mark unfinished jobs interrupted; optionally re-queue them.
    Returns list of job ids touched.
    """
    ensure_schema()
    touched: list[str] = []
    now = time.time()
    if not mark_interrupted:
        return touched
    with _connect() as cx:
        rows = cx.execute(
            "SELECT id, status FROM jobs WHERE status IN ('queued', 'running', 'paused')"
        ).fetchall()
        for row in rows:
            jid = str(row["id"])
            touched.append(jid)
            if resume_as_queued:
                cx.execute(
                    "UPDATE jobs SET status = 'queued', started_ts = NULL, worker_claim = NULL, "
                    "finished_ts = NULL, error = NULL WHERE id = ?",
                    (jid,),
                )
            else:
                cx.execute(
                    "UPDATE jobs SET status = 'interrupted', error = ?, finished_ts = ? WHERE id = ?",
                    ("server_restart", now, jid),
                )
        cx.commit()
    return touched


def upsert_job(row: dict[str, Any]) -> None:
    ensure_schema()
    latest = row.get("latest_results") or []
    fails = row.get("failures") or []
    tasks = row.get("task_states") or []
    fa = row.get("failure_analysis")
    latest_json = json.dumps(latest, ensure_ascii=False, default=str)[:1_500_000]
    fails_json = json.dumps(fails, ensure_ascii=False, default=str)[:500_000]
    tasks_json = json.dumps(tasks, ensure_ascii=False, default=str)[:500_000]
    fa_json = json.dumps(fa, ensure_ascii=False, default=str)[:200_000] if fa is not None else None
    with _connect() as cx:
        cx.execute(
            """
            INSERT INTO jobs (
              id, goal, status, created_ts, started_ts, finished_ts, deadline_ts,
              ok, clean_cycle, deadline_hit, error, progress_pct, max_seconds,
              fixed_goal_only, latest_results_json, failures_json, task_states_json,
              worker_claim, execution_ms, dispatch_mode, failure_analysis_json,
              user_id, organization_id, idempotency_key, version_id, slow_job, replay_source_job_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
              goal=excluded.goal,
              status=excluded.status,
              started_ts=excluded.started_ts,
              finished_ts=excluded.finished_ts,
              deadline_ts=excluded.deadline_ts,
              ok=excluded.ok,
              clean_cycle=excluded.clean_cycle,
              deadline_hit=excluded.deadline_hit,
              error=excluded.error,
              progress_pct=excluded.progress_pct,
              max_seconds=excluded.max_seconds,
              fixed_goal_only=excluded.fixed_goal_only,
              latest_results_json=excluded.latest_results_json,
              failures_json=excluded.failures_json,
              task_states_json=excluded.task_states_json,
              worker_claim=excluded.worker_claim,
              execution_ms=excluded.execution_ms,
              dispatch_mode=excluded.dispatch_mode,
              failure_analysis_json=excluded.failure_analysis_json,
              user_id=excluded.user_id,
              organization_id=excluded.organization_id,
              idempotency_key=COALESCE(excluded.idempotency_key, jobs.idempotency_key),
              version_id=COALESCE(excluded.version_id, jobs.version_id),
              slow_job=COALESCE(excluded.slow_job, jobs.slow_job),
              replay_source_job_id=COALESCE(excluded.replay_source_job_id, jobs.replay_source_job_id)
            """,
            (
                row["id"],
                row.get("goal", ""),
                row.get("status", "queued"),
                float(row.get("created_ts") or time.time()),
                row.get("started_ts"),
                row.get("finished_ts"),
                row.get("deadline_ts"),
                1 if row.get("ok") is True else (0 if row.get("ok") is False else None),
                1 if row.get("clean_cycle") is True else (0 if row.get("clean_cycle") is False else None),
                1 if row.get("deadline_hit") is True else (0 if row.get("deadline_hit") is False else None),
                row.get("error"),
                float(row.get("progress_pct") or 0.0),
                int(row.get("max_seconds") or 0) or None,
                1 if row.get("fixed_goal_only", True) else 0,
                latest_json,
                fails_json,
                tasks_json,
                row.get("worker_claim"),
                row.get("execution_ms"),
                str(row.get("dispatch_mode") or "inline"),
                fa_json,
                int(row.get("user_id") or 0),
                int(row.get("organization_id") or 0),
                (row.get("idempotency_key") or None),
                (row.get("version_id") or None),
                1 if row.get("slow_job") else 0,
                row.get("replay_source_job_id"),
            ),
        )
        cx.commit()


def load_all_jobs() -> dict[str, dict[str, Any]]:
    ensure_schema()
    out: dict[str, dict[str, Any]] = {}
    with _connect() as cx:
        rows = cx.execute("SELECT * FROM jobs ORDER BY created_ts DESC LIMIT 500").fetchall()
        for r in rows:
            d = dict(r)
            jid = str(d.pop("id"))
            for src, dest in (
                ("latest_results_json", "latest_results"),
                ("failures_json", "failures"),
                ("task_states_json", "task_states"),
            ):
                raw = d.pop(src, None)
                try:
                    parsed = json.loads(raw) if raw else []
                    d[dest] = parsed if isinstance(parsed, list) else []
                except json.JSONDecodeError:
                    d[dest] = []
            d["ok"] = True if d.get("ok") == 1 else (False if d.get("ok") == 0 else None)
            d["clean_cycle"] = True if d.get("clean_cycle") == 1 else (False if d.get("clean_cycle") == 0 else None)
            d["deadline_hit"] = True if d.get("deadline_hit") == 1 else (False if d.get("deadline_hit") == 0 else None)
            d["fixed_goal_only"] = bool(d.get("fixed_goal_only"))
            d["user_id"] = int(d.get("user_id") or 0)
            d["organization_id"] = int(d.get("organization_id") or 0)
            sj = d.pop("slow_job", None)
            d["slow_job"] = bool(sj == 1) if sj is not None else False
            raw_fa = d.pop("failure_analysis_json", None)
            try:
                d["failure_analysis"] = json.loads(raw_fa) if raw_fa else None
            except json.JSONDecodeError:
                d["failure_analysis"] = None
            d["id"] = jid
            out[jid] = d
    return out


def append_task_event(job_id: str, step_key: str, state: str, detail: dict[str, Any] | None = None) -> None:
    ensure_schema()
    with _connect() as cx:
        cx.execute(
            "INSERT INTO task_events (job_id, step_key, state, ts, detail_json) VALUES (?,?,?,?,?)",
            (
                job_id,
                step_key,
                state,
                time.time(),
                json.dumps(detail or {}, ensure_ascii=False, default=str)[:100_000],
            ),
        )
        cx.commit()


def claim_next_worker_job(worker_id: str, organization_id: int | None = None) -> str | None:
    """
    Claim the next queued worker-dispatched job.

    When ``organization_id`` is set (single-tenant worker), FIFO within that org only.
    When unset and ``THIRAMAI_GOAL_FAIR_QUEUE_RR`` is on, round-robin across tenants
    (fairness); otherwise global FIFO by ``created_ts``.
    """
    ensure_schema()
    wid = (worker_id or "").strip()[:128] or "worker"
    now = time.time()

    def _claim_fifo_global(cx: sqlite3.Connection) -> str | None:
        row = cx.execute(
            "SELECT id FROM jobs WHERE status = 'queued' AND dispatch_mode = 'worker' "
            "ORDER BY created_ts ASC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        jid = str(row["id"])
        cx.execute(
            "UPDATE jobs SET status = 'running', started_ts = ?, worker_claim = ? WHERE id = ?",
            (now, wid, jid),
        )
        return jid

    def _claim_fifo_org(cx: sqlite3.Connection, oid: int) -> str | None:
        row = cx.execute(
            "SELECT id FROM jobs WHERE status = 'queued' AND dispatch_mode = 'worker' "
            "AND organization_id = ? ORDER BY created_ts ASC LIMIT 1",
            (int(oid),),
        ).fetchone()
        if not row:
            return None
        jid = str(row["id"])
        cx.execute(
            "UPDATE jobs SET status = 'running', started_ts = ?, worker_claim = ? WHERE id = ?",
            (now, wid, jid),
        )
        return jid

    def _claim_round_robin(cx: sqlite3.Connection) -> str | None:
        rows = cx.execute(
            "SELECT DISTINCT organization_id FROM jobs WHERE status = 'queued' "
            "AND dispatch_mode = 'worker' ORDER BY organization_id ASC"
        ).fetchall()
        orgs = [int(r["organization_id"]) for r in rows]
        if not orgs:
            return None
        cur = cx.execute("SELECT last_organization_id FROM fair_queue_rr WHERE id = 1").fetchone()
        last = cur["last_organization_id"] if cur else None
        if last is not None and last in orgs:
            start_idx = (orgs.index(int(last)) + 1) % len(orgs)
        else:
            start_idx = 0
        for step in range(len(orgs)):
            oid = orgs[(start_idx + step) % len(orgs)]
            row = cx.execute(
                "SELECT id FROM jobs WHERE status = 'queued' AND dispatch_mode = 'worker' "
                "AND organization_id = ? ORDER BY created_ts ASC LIMIT 1",
                (oid,),
            ).fetchone()
            if not row:
                continue
            jid = str(row["id"])
            cx.execute(
                "UPDATE jobs SET status = 'running', started_ts = ?, worker_claim = ? WHERE id = ?",
                (now, wid, jid),
            )
            cx.execute(
                """
                INSERT INTO fair_queue_rr (id, last_organization_id) VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET last_organization_id = excluded.last_organization_id
                """,
                (oid,),
            )
            return jid
        return None

    with _connect() as cx:
        cx.execute("BEGIN IMMEDIATE")
        try:
            if organization_id is not None:
                jid = _claim_fifo_org(cx, int(organization_id))
            elif THIRAMAI_GOAL_FAIR_QUEUE_RR:
                jid = _claim_round_robin(cx)
            else:
                jid = _claim_fifo_global(cx)
            cx.commit()
            return jid
        except Exception:
            cx.execute("ROLLBACK")
            raise


def append_connector_audit(action_type: str, ok: bool, detail: dict[str, Any]) -> None:
    ensure_schema()
    with _connect() as cx:
        cx.execute(
            "INSERT INTO connector_audit (ts, action_type, ok, detail_json) VALUES (?,?,?,?)",
            (time.time(), action_type[:128], 1 if ok else 0, json.dumps(detail, ensure_ascii=False, default=str)[:50_000]),
        )
        cx.commit()


def load_job(job_id: str) -> dict[str, Any] | None:
    ensure_schema()
    with _connect() as cx:
        row = cx.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        jid = str(d.pop("id"))
        d["id"] = jid
        for src, dest in (
            ("latest_results_json", "latest_results"),
            ("failures_json", "failures"),
            ("task_states_json", "task_states"),
        ):
            raw = d.pop(src, None)
            try:
                parsed = json.loads(raw) if raw else []
                d[dest] = parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                d[dest] = []
        d["ok"] = True if d.get("ok") == 1 else (False if d.get("ok") == 0 else None)
        d["clean_cycle"] = True if d.get("clean_cycle") == 1 else (False if d.get("clean_cycle") == 0 else None)
        d["deadline_hit"] = True if d.get("deadline_hit") == 1 else (False if d.get("deadline_hit") == 0 else None)
        d["fixed_goal_only"] = bool(d.get("fixed_goal_only"))
        d["user_id"] = int(d.get("user_id") or 0)
        d["organization_id"] = int(d.get("organization_id") or 0)
        sj = d.pop("slow_job", None)
        d["slow_job"] = bool(sj == 1) if sj is not None else False
        raw_fa = d.pop("failure_analysis_json", None)
        try:
            d["failure_analysis"] = json.loads(raw_fa) if raw_fa else None
        except json.JSONDecodeError:
            d["failure_analysis"] = None
        return d


def get_job_status(job_id: str) -> str | None:
    ensure_schema()
    with _connect() as cx:
        row = cx.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return str(row["status"]) if row else None


def heartbeat_worker(
    worker_id: str,
    status: str,
    current_job_id: str | None = None,
    *,
    organization_id: int = 0,
    release_version: str | None = None,
) -> None:
    ensure_schema()
    from thiramai.config import THIRAMAI_VERSION_ID

    wid = (worker_id or "").strip()[:128] or "unknown"
    oid = int(organization_id)
    rv = ((release_version or THIRAMAI_VERSION_ID) or "")[:128] or None
    with _connect() as cx:
        cx.execute(
            """
            INSERT INTO worker_heartbeats (
              worker_id, ts, status, current_job_id, organization_id, release_version
            )
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(worker_id) DO UPDATE SET
              ts=excluded.ts,
              status=excluded.status,
              current_job_id=excluded.current_job_id,
              organization_id=excluded.organization_id,
              release_version=COALESCE(excluded.release_version, worker_heartbeats.release_version)
            """,
            (wid, time.time(), status[:32], current_job_id, oid, rv),
        )
        cx.commit()


def list_worker_heartbeats(organization_id: int | None = None) -> list[dict[str, Any]]:
    ensure_schema()
    with _connect() as cx:
        if organization_id is not None:
            rows = cx.execute(
                "SELECT worker_id, ts, status, current_job_id, organization_id, release_version "
                "FROM worker_heartbeats WHERE organization_id = ? ORDER BY ts DESC",
                (int(organization_id),),
            ).fetchall()
        else:
            rows = cx.execute(
                "SELECT worker_id, ts, status, current_job_id, organization_id, release_version "
                "FROM worker_heartbeats ORDER BY ts DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def count_active_jobs() -> int:
    ensure_schema()
    with _connect() as cx:
        row = cx.execute(
            "SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running','paused')"
        ).fetchone()
        return int(row[0]) if row else 0


def list_jobs_for_queue(organization_id: int | None = None) -> list[dict[str, Any]]:
    """Recent jobs in active states for queue inspection (optionally scoped to one org)."""
    ensure_schema()
    with _connect() as cx:
        if organization_id is not None:
            rows = cx.execute(
                """
                SELECT id, goal, status, created_ts, started_ts, finished_ts,
                       worker_claim, dispatch_mode, progress_pct, user_id, organization_id
                FROM jobs
                WHERE status IN ('queued', 'running', 'paused') AND organization_id = ?
                ORDER BY created_ts ASC
                LIMIT 200
                """,
                (int(organization_id),),
            ).fetchall()
        else:
            rows = cx.execute(
                """
                SELECT id, goal, status, created_ts, started_ts, finished_ts,
                       worker_claim, dispatch_mode, progress_pct, user_id, organization_id
                FROM jobs
                WHERE status IN ('queued', 'running', 'paused')
                ORDER BY created_ts ASC
                LIMIT 200
                """
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            jid = str(d.pop("id"))
            d["id"] = jid
            out.append(d)
        return out
