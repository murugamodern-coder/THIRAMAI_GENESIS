"""
Background execution of THIRAMAI autonomous goals for HTTP API (POST /ai/goal).

Persists state to SQLite when ``THIRAMAI_JOB_SQLITE`` is enabled. Optional worker dispatch
(``THIRAMAI_GOAL_WORKER_DISPATCH``) defers execution to ``python -m thiramai.worker``.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

from thiramai.config import (
    THIRAMAI_GOAL_MAX_SECONDS,
    THIRAMAI_GOAL_REJECT_ON_OVERLOAD,
    THIRAMAI_GOAL_SLOW_JOB_MS,
    THIRAMAI_GOAL_WORKER_DISPATCH,
    THIRAMAI_JOB_SQLITE,
    THIRAMAI_MAX_CONCURRENT_GOAL_JOBS,
    THIRAMAI_VERSION_ID,
)
from thiramai.timeutil import non_negative_ms, utc_iso_from_unix

_log = logging.getLogger("thiramai.goal_jobs")

_executor = ThreadPoolExecutor(
    max_workers=max(2, THIRAMAI_MAX_CONCURRENT_GOAL_JOBS),
    thread_name_prefix="thiramai-goal",
)
_jobs_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_history: deque[str] = deque(maxlen=500)
_persistence_initialized = False

_JOB_LOGS: dict[str, deque[dict[str, Any]]] = {}
_active_cores: dict[str, Any] = {}
_poll_ts: dict[str, float] = {}
_accepting_new_jobs = True
_executor_shutdown_done = False

# When SQLite is off, idempotency keys map here (lost on restart).
_idempotency_memory: dict[tuple[int, int, str], str] = {}


class IdempotencyConflictError(ValueError):
    """Same ``idempotency_key`` reused with different goal or tenant-bound job mismatch."""


def _warn_or_reject_job_version_mismatch(row: dict[str, Any]) -> None:
    """Phase 56: stored ``version_id`` vs current binary — warn or reject."""
    jv = (row.get("version_id") or "").strip()
    if not jv or jv == THIRAMAI_VERSION_ID:
        return
    jid = row.get("id")
    _log.warning(
        "job_version_mismatch job_id=%s job_version=%s current_version=%s",
        jid,
        jv,
        THIRAMAI_VERSION_ID,
    )
    if (os.getenv("THIRAMAI_REJECT_JOB_VERSION_MISMATCH") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        raise ValueError(
            f"job version mismatch: job has {jv!r}, this process is {THIRAMAI_VERSION_ID!r}"
        )


def _mark_slow_job_if_needed(job_id: str, execution_ms: float) -> None:
    if THIRAMAI_GOAL_SLOW_JOB_MS <= 0:
        return
    if execution_ms < float(THIRAMAI_GOAL_SLOW_JOB_MS):
        return
    with _jobs_lock:
        r = _jobs.get(job_id)
        if r is not None:
            r["slow_job"] = True
    append_job_log(
        job_id,
        "warning",
        "slow_job",
        execution_ms=round(execution_ms, 2),
        threshold_ms=THIRAMAI_GOAL_SLOW_JOB_MS,
    )
    try:
        from thiramai.runtime import ops_alerts

        ops_alerts.emit_slow_goal_job(job_id, execution_ms, float(THIRAMAI_GOAL_SLOW_JOB_MS))
    except Exception:
        pass


def _persist(row: dict[str, Any]) -> None:
    if not THIRAMAI_JOB_SQLITE:
        return
    try:
        from thiramai.runtime.sqlite_job_store import upsert_job

        upsert_job(row)
    except Exception:
        pass


def append_job_log(job_id: str, level: str, message: str, **extra: Any) -> None:
    rec: dict[str, Any] = {"ts": time.time(), "level": level, "message": message}
    if extra:
        rec["extra"] = extra
    with _jobs_lock:
        buf = _JOB_LOGS.setdefault(job_id, deque(maxlen=800))
    buf.append(rec)


def get_job_logs(job_id: str, *, tail: int = 200) -> list[dict[str, Any]]:
    lim = max(1, min(int(tail), 800))
    with _jobs_lock:
        buf = _JOB_LOGS.get(job_id)
        if not buf:
            return []
        return list(buf)[-lim:]


def register_active_core(job_id: str, core: Any) -> None:
    _active_cores[job_id] = core


def unregister_active_core(job_id: str) -> None:
    _active_cores.pop(job_id, None)


def refresh_job_status_from_sqlite(job_id: str) -> None:
    if not THIRAMAI_JOB_SQLITE:
        return
    try:
        from thiramai.runtime.sqlite_job_store import get_job_status

        st = get_job_status(job_id)
        if not st:
            return
        with _jobs_lock:
            row = _jobs.get(job_id)
            if row is not None:
                row["status"] = st
    except Exception:
        pass


def poll_job_control(job_id: str) -> Literal["cancel", "pause"] | None:
    """Worker / JarvisCore cooperative control: cancel aborts; pause yields between waves."""
    now = time.time()
    if now - _poll_ts.get(job_id, 0) >= 0.75:
        refresh_job_status_from_sqlite(job_id)
        _poll_ts[job_id] = now
    with _jobs_lock:
        st = (_jobs.get(job_id) or {}).get("status")
    if st == "cancelled":
        return "cancel"
    if st == "paused":
        return "pause"
    return None


def display_status(raw: str | None) -> str:
    if raw == "queued":
        return "pending"
    return str(raw or "")


def public_job_view(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["status"] = display_status(out.get("status"))
    out.pop("idempotency_key", None)
    if "version_id" not in out or not out.get("version_id"):
        out["version_id"] = THIRAMAI_VERSION_ID
    for ts_key in ("created_ts", "started_ts", "finished_ts"):
        tv = out.get(ts_key)
        if tv is not None:
            try:
                out[f"{ts_key}_utc"] = utc_iso_from_unix(float(tv))
            except (TypeError, ValueError):
                out[f"{ts_key}_utc"] = None
    return out


def user_can_access_goal_job(principal: Any, row: dict[str, Any]) -> bool:
    """Tenant isolation: same org; viewer sees own jobs only; owner/admin/manager see org-wide."""
    try:
        oid = int(row.get("organization_id") or 0)
        if oid != int(principal.organization_id):
            return False
        rn = str(principal.role_name).lower()
        if rn in ("owner", "admin", "manager"):
            return True
        return int(row.get("user_id") or 0) == int(principal.id)
    except Exception:
        return False


def count_active_goal_jobs() -> int:
    if THIRAMAI_JOB_SQLITE:
        try:
            from thiramai.runtime.sqlite_job_store import count_active_jobs

            return int(count_active_jobs())
        except Exception:
            pass
    with _jobs_lock:
        return sum(
            1
            for j in _jobs.values()
            if j.get("status") in ("queued", "running", "paused")
        )


def begin_shutdown(*, accept_new_jobs: bool = False) -> None:
    global _accepting_new_jobs
    _accepting_new_jobs = accept_new_jobs


def is_accepting_jobs() -> bool:
    return _accepting_new_jobs


def shutdown_graceful(*, timeout_sec: float = 45.0) -> None:
    """Stop accepting work, signal in-process cores, wait for thread pool (best-effort)."""
    global _executor_shutdown_done
    begin_shutdown(accept_new_jobs=False)
    with _jobs_lock:
        cores = list(_active_cores.items())
    for _jid, core in cores:
        try:
            core.request_stop()
        except Exception:
            pass
    if _executor_shutdown_done:
        return
    try:
        _executor.shutdown(wait=True, cancel_futures=False)
    except Exception:
        pass
    _executor_shutdown_done = True


def cancel_job(job_id: str) -> dict[str, Any]:
    initialize_persistence()
    get_job(job_id)
    core = None
    with _jobs_lock:
        row = _jobs.get(job_id)
        if row is None:
            return {"ok": False, "error": "not_found"}
        prev = row.get("status")
        if prev in ("completed", "failed", "cancelled", "interrupted"):
            return {"ok": False, "error": "terminal_state", "status": display_status(prev)}
        row["status"] = "cancelled"
        row["finished_ts"] = time.time()
        row["error"] = row.get("error") or "cancelled_by_operator"
        row["progress_pct"] = float(row.get("progress_pct") or 0.0)
        core = _active_cores.get(job_id)
        snap = dict(row)
    _persist(snap)
    append_job_log(job_id, "info", "job_cancelled")
    if core is not None:
        try:
            core.request_stop()
        except Exception:
            pass
    return {"ok": True, "job_id": job_id}


def pause_job(job_id: str) -> dict[str, Any]:
    initialize_persistence()
    get_job(job_id)
    with _jobs_lock:
        row = _jobs.get(job_id)
        if row is None:
            return {"ok": False, "error": "not_found"}
        if row.get("status") != "running":
            return {"ok": False, "error": "not_running", "status": display_status(row.get("status"))}
        row["status"] = "paused"
        snap = dict(row)
    _persist(snap)
    append_job_log(job_id, "info", "job_paused")
    return {"ok": True, "job_id": job_id}


def resume_job(job_id: str) -> dict[str, Any]:
    initialize_persistence()
    get_job(job_id)
    with _jobs_lock:
        row = _jobs.get(job_id)
        if row is None:
            return {"ok": False, "error": "not_found"}
        if row.get("status") != "paused":
            return {"ok": False, "error": "not_paused", "status": display_status(row.get("status"))}
        row["status"] = "running"
        snap = dict(row)
    _persist(snap)
    append_job_log(job_id, "info", "job_resumed")
    return {"ok": True, "job_id": job_id}


def queue_snapshot(*, organization_id: int | None = None) -> dict[str, Any]:
    initialize_persistence()
    pending: list[dict[str, Any]] = []
    running: list[dict[str, Any]] = []
    paused: list[dict[str, Any]] = []
    if THIRAMAI_JOB_SQLITE:
        try:
            from thiramai.runtime.sqlite_job_store import list_jobs_for_queue

            for row in list_jobs_for_queue(organization_id):
                st = row.get("status")
                slim = {
                    "id": row.get("id"),
                    "goal": (row.get("goal") or "")[:200],
                    "status": display_status(st),
                    "created_ts": row.get("created_ts"),
                    "started_ts": row.get("started_ts"),
                    "worker_claim": row.get("worker_claim"),
                    "dispatch_mode": row.get("dispatch_mode"),
                    "progress_pct": row.get("progress_pct"),
                    "user_id": row.get("user_id"),
                    "organization_id": row.get("organization_id"),
                }
                if st == "queued":
                    pending.append(slim)
                elif st == "running":
                    running.append(slim)
                elif st == "paused":
                    paused.append(slim)
            return {"ok": True, "pending": pending, "running": running, "paused": paused}
        except Exception:
            pass
    with _jobs_lock:
        for j in _jobs.values():
            if organization_id is not None and int(j.get("organization_id") or 0) != int(organization_id):
                continue
            st = j.get("status")
            slim = {
                "id": j.get("id"),
                "goal": str(j.get("goal") or "")[:200],
                "status": display_status(st),
                "created_ts": j.get("created_ts"),
                "started_ts": j.get("started_ts"),
                "worker_claim": j.get("worker_claim"),
                "dispatch_mode": j.get("dispatch_mode"),
                "progress_pct": j.get("progress_pct"),
                "user_id": j.get("user_id"),
                "organization_id": j.get("organization_id"),
            }
            if st == "queued":
                pending.append(slim)
            elif st == "running":
                running.append(slim)
            elif st == "paused":
                paused.append(slim)
    return {"ok": True, "pending": pending, "running": running, "paused": paused}


def workers_snapshot(*, stale_after_sec: float = 45.0, organization_id: int | None = None) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    now = time.time()
    if THIRAMAI_JOB_SQLITE:
        try:
            from thiramai.runtime.sqlite_job_store import list_worker_heartbeats

            for r in list_worker_heartbeats(organization_id):
                wid = str(r.get("worker_id") or "")
                ts = float(r.get("ts") or 0)
                age = now - ts
                status_raw = str(r.get("status") or "")
                if age > stale_after_sec:
                    health = "dead"
                elif status_raw == "busy":
                    health = "busy"
                else:
                    health = "idle"
                rows.append(
                    {
                        "worker_id": wid,
                        "last_heartbeat_ts": ts,
                        "age_sec": round(age, 3),
                        "current_job_id": r.get("current_job_id"),
                        "reported_status": status_raw,
                        "health": health,
                        "organization_id": r.get("organization_id"),
                    }
                )
        except Exception:
            pass
    return {"ok": True, "workers": rows}


def initialize_persistence() -> None:
    """Call once at API startup: recover interrupted jobs and merge SQLite into memory."""
    global _persistence_initialized, _jobs
    if _persistence_initialized or not THIRAMAI_JOB_SQLITE:
        _persistence_initialized = True
        return
    try:
        from thiramai.runtime import sqlite_maintenance

        sqlite_maintenance.ensure_jobs_database_healthy()
    except Exception:
        pass
    try:
        from thiramai.config import THIRAMAI_JOB_RECOVER_INTERRUPTED, THIRAMAI_JOB_RESUME_QUEUED
        from thiramai.runtime.sqlite_job_store import load_all_jobs, recover_after_restart

        recover_after_restart(THIRAMAI_JOB_RECOVER_INTERRUPTED, THIRAMAI_JOB_RESUME_QUEUED)
        loaded = load_all_jobs()
        with _jobs_lock:
            for jid, row in loaded.items():
                _jobs[jid] = row
                if jid not in _history:
                    _history.appendleft(jid)
    except Exception:
        pass
    _persistence_initialized = True


def _validate_idempotent_match(
    job_id: str,
    *,
    goal_text: str,
    organization_id: int,
    user_id: int,
) -> None:
    """Ensure stored job matches this submission (phase 49)."""
    row = get_job(job_id)
    if row is None:
        raise IdempotencyConflictError("idempotency_key refers to a missing job")
    oid = int(organization_id)
    uid = int(user_id)
    if int(row.get("organization_id") or 0) != oid or int(row.get("user_id") or 0) != uid:
        raise IdempotencyConflictError(
            "idempotency_key conflicts with organization_id or user_id for the existing job"
        )
    if str(row.get("goal") or "").strip() != goal_text.strip():
        raise IdempotencyConflictError(
            "idempotency_key already used with a different goal"
        )


def submit_goal(
    goal: str,
    *,
    max_seconds: int | None = None,
    fixed_goal_only: bool = True,
    user_id: int = 0,
    organization_id: int = 0,
    idempotency_key: str | None = None,
    force_refresh: bool = False,
    replay_from_job_id: str | None = None,
) -> dict[str, Any]:
    """
    Queue a goal run.

    Returns a dict with at least ``job_id``. May set ``idempotent_replay`` or ``from_cache``.
    When ``THIRAMAI_GOAL_WORKER_DISPATCH`` is true, only persists — worker process executes.
    """
    initialize_persistence()
    if not _accepting_new_jobs:
        raise ValueError("server is shutting down; not accepting new goals")

    text = (goal or "").strip()
    if not text:
        raise ValueError("goal must be non-empty")

    oid = int(organization_id)
    uid = int(user_id)
    ikey = (idempotency_key or "").strip()[:512] or None
    if ikey:
        found: str | None = None
        if THIRAMAI_JOB_SQLITE:
            try:
                from thiramai.runtime.sqlite_job_store import job_id_for_idempotency_key

                found = job_id_for_idempotency_key(oid, uid, ikey)
            except Exception:
                found = None
        else:
            found = _idempotency_memory.get((oid, uid, ikey))
        if found:
            _validate_idempotent_match(found, goal_text=text, organization_id=oid, user_id=uid)
            return {"job_id": found, "idempotent_replay": True, "from_cache": False}

    if not force_refresh:
        try:
            from thiramai.runtime.goal_result_cache import get_cached_job_id

            cj = get_cached_job_id(oid, uid, text)
            if cj:
                row = get_job(cj)
                if row and row.get("status") == "completed" and row.get("ok") is True:
                    return {"job_id": cj, "idempotent_replay": False, "from_cache": True}
        except Exception:
            pass

    if THIRAMAI_GOAL_REJECT_ON_OVERLOAD:
        try:
            from core.stability.resource_monitor import is_overloaded

            if is_overloaded():
                raise ValueError("system overloaded; try again shortly")
        except ValueError:
            raise
        except Exception:
            pass
    if count_active_goal_jobs() >= THIRAMAI_MAX_CONCURRENT_GOAL_JOBS:
        raise ValueError(
            f"maximum concurrent goal jobs ({THIRAMAI_MAX_CONCURRENT_GOAL_JOBS}) reached"
        )
    try:
        from thiramai.runtime.billing_quota import assert_goal_submit_allowed

        assert_goal_submit_allowed(int(organization_id), int(user_id))
    except ValueError:
        raise
    except Exception:
        pass

    job_id = uuid.uuid4().hex
    budget = max(30, int(max_seconds or THIRAMAI_GOAL_MAX_SECONDS))
    deadline = time.time() + float(budget)
    dispatch = "worker" if THIRAMAI_GOAL_WORKER_DISPATCH else "inline"

    snapshot: dict[str, Any] = {
        "id": job_id,
        "goal": text,
        "status": "queued",
        "created_ts": time.time(),
        "started_ts": None,
        "finished_ts": None,
        "ok": None,
        "clean_cycle": None,
        "deadline_ts": deadline,
        "error": None,
        "latest_results": [],
        "failures": [],
        "task_states": [],
        "progress_pct": 0.0,
        "max_seconds": budget,
        "fixed_goal_only": fixed_goal_only,
        "dispatch_mode": dispatch,
        "worker_claim": None,
        "execution_ms": None,
        "user_id": int(user_id),
        "organization_id": int(organization_id),
        "idempotency_key": ikey,
        "version_id": THIRAMAI_VERSION_ID,
        "slow_job": False,
    }
    rf = (replay_from_job_id or "").strip()
    if rf:
        snapshot["replay_source_job_id"] = rf[:64]
    if ikey and not THIRAMAI_JOB_SQLITE:
        _idempotency_memory[(oid, uid, ikey)] = job_id
    with _jobs_lock:
        _jobs[job_id] = snapshot
        _history.appendleft(job_id)
    _persist(snapshot)
    try:
        from thiramai.runtime.billing_quota import record_job_submitted

        record_job_submitted(int(organization_id), int(user_id))
    except Exception:
        pass
    append_job_log(job_id, "info", "job_submitted", dispatch=dispatch)

    if dispatch == "worker":
        return {"job_id": job_id, "idempotent_replay": False, "from_cache": False}

    _executor.submit(_run_job_thread, job_id, text, fixed_goal_only, deadline)
    return {"job_id": job_id, "idempotent_replay": False, "from_cache": False}


def _run_job_thread(job_id: str, text: str, fixed_goal_only: bool, deadline: float) -> None:
    start_mono = time.perf_counter()
    core_holder: list[Any] = []
    stop_timer = threading.Event()

    def _tick() -> None:
        while not stop_timer.wait(12.0):
            try:
                core = core_holder[0] if core_holder else None
                if core is None:
                    continue
                states: list[dict[str, Any]] = []
                for i, rec in enumerate(core.latest_results[-40:]):
                    tid = rec.get("task_id", str(i))
                    rev = (rec.get("review") or {}).get("status", "")
                    states.append({"task_id": tid, "state": "success" if rev == "pass" else "failed_or_pending"})
                pct = min(99.0, float(len(core.latest_results) * 5))
                with _jobs_lock:
                    row = _jobs.get(job_id)
                    if row and row.get("status") == "running":
                        row["task_states"] = states
                        row["progress_pct"] = pct
                        row["latest_results"] = list(core.latest_results[-20:])
                        row["failures"] = list(core.failures[-10:])
                _persist(_jobs.get(job_id) or {})
            except Exception:
                pass

    poller = threading.Thread(target=_tick, name=f"job-progress-{job_id[:8]}", daemon=True)

    def _execute_goal_cycle() -> None:
        from thiramai.main import JarvisCore
        from thiramai.runtime import ai_observability
        from thiramai.runtime.sqlite_job_store import append_task_event

        core = JarvisCore(text, fixed_goal_only=fixed_goal_only, job_id=job_id)
        core_holder.append(core)
        register_active_core(job_id, core)
        core.execution_deadline = deadline
        poller.start()
        append_job_log(job_id, "info", "job_execution_started")
        cycle_id = int(time.time())
        append_task_event(job_id, "cycle", "running", {"cycle_id": cycle_id})
        cycle_ok = core._run_autonomous_cycle(cycle_id)  # noqa: SLF001
        elapsed_ms = non_negative_ms((time.perf_counter() - start_mono) * 1000.0)
        ai_observability.record_job_completed(elapsed_ms, ok=bool(cycle_ok))
        with _jobs_lock:
            row = _jobs.get(job_id)
            if row is not None:
                if row.get("status") == "cancelled":
                    row["finished_ts"] = time.time()
                    row["ok"] = False
                    row["error"] = row.get("error") or "cancelled_by_operator"
                    row["execution_ms"] = elapsed_ms
                    row["latest_results"] = list(core.latest_results[-25:])
                    row["failures"] = list(core.failures[-15:])
                    row["task_states"] = _derive_final_states(core)
                    append_job_log(job_id, "info", "job_stopped_cancelled")
                    _mark_slow_job_if_needed(job_id, elapsed_ms)
                else:
                    row["status"] = "completed"
                    row["finished_ts"] = time.time()
                    row["ok"] = bool(cycle_ok)
                    row["clean_cycle"] = bool(getattr(core, "_last_cycle_clean", False))
                    row["deadline_hit"] = bool(getattr(core, "_last_cycle_deadline", False))
                    row["latest_results"] = list(core.latest_results[-25:])
                    row["failures"] = list(core.failures[-15:])
                    row["progress_pct"] = 100.0
                    row["execution_ms"] = elapsed_ms
                    row["task_states"] = _derive_final_states(core)
                    append_job_log(job_id, "info", "job_completed", ok=cycle_ok)
                    _mark_slow_job_if_needed(job_id, elapsed_ms)
        append_task_event(job_id, "cycle", "success" if cycle_ok else "failed", {"ms": elapsed_ms})
        _persist(_jobs.get(job_id) or {})
        _terminal = None
        with _jobs_lock:
            _terminal = (_jobs.get(job_id) or {}).get("status")
        if not cycle_ok and _terminal != "cancelled":
            try:
                from thiramai.runtime.failure_analysis import analyze_job_failure

                hint = analyze_job_failure(
                    None,
                    message="cycle_completed_unclean",
                    job_id=job_id,
                    failing_step=None,
                    extra_context={"deadline_hit": getattr(core, "_last_cycle_deadline", False)},
                )
                with _jobs_lock:
                    r2 = _jobs.get(job_id)
                    if r2 is not None:
                        r2["failure_analysis"] = hint
                _persist(_jobs.get(job_id) or {})
            except Exception:
                pass

    now_started = time.time()
    with _jobs_lock:
        row = _jobs.get(job_id)
        if row is not None:
            row["status"] = "running"
            row["started_ts"] = now_started
            created = float(row.get("created_ts") or now_started)
            qwait_ms = non_negative_ms((now_started - created) * 1000.0)
        else:
            qwait_ms = 0.0
    try:
        from thiramai.runtime import ai_observability

        ai_observability.record_queue_wait_ms(qwait_ms)
    except Exception:
        pass
    _persist(_jobs.get(job_id) or {})

    try:
        from thiramai.runtime.request_context import goal_execution_context

        with _jobs_lock:
            row_ctx = dict(_jobs.get(job_id) or {})
        oid = int(row_ctx.get("organization_id") or 0)
        uid = int(row_ctx.get("user_id") or 0)
        with goal_execution_context(oid, uid, job_id):
            _execute_goal_cycle()
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = non_negative_ms((time.perf_counter() - start_mono) * 1000.0)
        try:
            from thiramai.runtime import ai_observability

            ai_observability.record_job_completed(elapsed_ms, ok=False)
            ai_observability.record_failure(str(exc), extra={"job_id": job_id})
        except Exception:
            pass
        try:
            from thiramai.runtime.failure_analysis import analyze_job_failure

            fa = analyze_job_failure(exc, job_id=job_id, failing_step=None)
            append_job_log(job_id, "error", str(exc), analysis=fa.get("error_type"))
            with _jobs_lock:
                row = _jobs.get(job_id)
                if row is not None:
                    row["failure_analysis"] = fa
        except Exception:
            fa = None
        with _jobs_lock:
            row = _jobs.get(job_id)
            if row is not None:
                row["status"] = "failed"
                row["finished_ts"] = time.time()
                row["ok"] = False
                row["error"] = str(exc)
                row["execution_ms"] = elapsed_ms
        _mark_slow_job_if_needed(job_id, elapsed_ms)
        try:
            from thiramai.runtime.sqlite_job_store import append_task_event

            append_task_event(job_id, "cycle", "error", {"error": str(exc)})
        except Exception:
            pass
        _persist(_jobs.get(job_id) or {})
    finally:
        unregister_active_core(job_id)
        stop_timer.set()
        try:
            from thiramai.core.memory import MemoryStore

            with _jobs_lock:
                snap = dict(_jobs.get(job_id) or {})
            MemoryStore().record_goal_job_outcome(
                text,
                {
                    "job_id": job_id,
                    "status": snap.get("status"),
                    "ok": snap.get("ok"),
                    "clean_cycle": snap.get("clean_cycle"),
                    "deadline_hit": snap.get("deadline_hit"),
                    "error": snap.get("error"),
                },
            )
            try:
                from thiramai.runtime.goal_result_cache import remember as cache_remember_goal

                if (
                    snap.get("status") == "completed"
                    and snap.get("ok") is True
                    and str(snap.get("goal") or "").strip()
                ):
                    cache_remember_goal(
                        int(snap.get("organization_id") or 0),
                        int(snap.get("user_id") or 0),
                        str(snap.get("goal") or ""),
                        job_id,
                    )
            except Exception:
                pass
        except Exception:
            pass


def _derive_final_states(core: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rec in core.latest_results[-60:]:
        tid = rec.get("task_id", "")
        st = "success"
        rev = (rec.get("review") or {}).get("status", "")
        if rev != "pass":
            st = "failed"
        out.append({"task_id": tid, "state": st})
    return out


def run_persisted_job(job_id: str) -> None:
    """Execute a single job by id (worker entry). Loads goal from SQLite/memory."""
    initialize_persistence()
    row = get_job(job_id)
    if not row:
        return
    try:
        _warn_or_reject_job_version_mismatch(row)
    except ValueError as exc:
        msg = str(exc)
        append_job_log(job_id, "error", "job_rejected_version_mismatch", detail=msg)
        with _jobs_lock:
            r2 = _jobs.get(job_id)
            if r2 is not None:
                r2["status"] = "failed"
                r2["finished_ts"] = time.time()
                r2["ok"] = False
                r2["error"] = msg
        _persist(_jobs.get(job_id) or {})
        return
    text = str(row.get("goal") or "").strip()
    if not text:
        return
    fixed = bool(row.get("fixed_goal_only", True))
    deadline_ts = float(row.get("deadline_ts") or (time.time() + THIRAMAI_GOAL_MAX_SECONDS))
    _run_job_thread(job_id, text, fixed, deadline_ts)


def replay_goal_job(
    source_job_id: str,
    *,
    user_id: int,
    organization_id: int,
) -> dict[str, Any]:
    """Clone inputs from an existing job and queue a fresh run (phase 57)."""
    sid = (source_job_id or "").strip()
    if not sid:
        raise ValueError("source job_id required")
    row = get_job(sid)
    if not row:
        raise ValueError("job not found")
    if int(row.get("organization_id") or 0) != int(organization_id):
        raise ValueError("access denied")
    return submit_goal(
        str(row.get("goal") or "").strip(),
        max_seconds=int(row.get("max_seconds") or THIRAMAI_GOAL_MAX_SECONDS),
        fixed_goal_only=bool(row.get("fixed_goal_only", True)),
        user_id=int(user_id),
        organization_id=int(organization_id),
        replay_from_job_id=sid,
    )


def get_job(job_id: str) -> dict[str, Any] | None:
    initialize_persistence()
    with _jobs_lock:
        mem = _jobs.get(job_id)
        if mem is not None:
            return dict(mem)
    if THIRAMAI_JOB_SQLITE:
        try:
            from thiramai.runtime.sqlite_job_store import load_job

            disk = load_job(job_id)
            if disk:
                with _jobs_lock:
                    _jobs[job_id] = disk
                return dict(disk)
        except Exception:
            pass
    return None


def list_recent_jobs(limit: int = 25) -> list[dict[str, Any]]:
    """Unfiltered (legacy / admin tools). Prefer ``list_recent_jobs_for_principal`` for API."""
    initialize_persistence()
    lim = max(1, min(int(limit), 100))
    with _jobs_lock:
        out: list[dict[str, Any]] = []
        for jid in list(_history):
            row = _jobs.get(jid)
            if row:
                slim = {
                    "id": row["id"],
                    "goal": row.get("goal"),
                    "status": display_status(row.get("status")),
                    "created_ts": row.get("created_ts"),
                    "finished_ts": row.get("finished_ts"),
                    "ok": row.get("ok"),
                    "clean_cycle": row.get("clean_cycle"),
                    "error": row.get("error"),
                    "progress_pct": row.get("progress_pct"),
                    "dispatch_mode": row.get("dispatch_mode"),
                }
                out.append(slim)
            if len(out) >= lim:
                break
        return out


def list_recent_jobs_for_principal(principal: Any, limit: int = 25) -> list[dict[str, Any]]:
    """Tenant- and user-scoped job list (viewer: own jobs; owner/admin/manager: org-wide)."""
    initialize_persistence()
    lim = max(1, min(int(limit), 100))
    try:
        oid = int(principal.organization_id)
        uid = int(principal.id)
        rn = str(principal.role_name).lower()
        privileged = rn in ("owner", "admin", "manager")
    except Exception:
        return []
    rows_out: list[dict[str, Any]] = []
    if THIRAMAI_JOB_SQLITE:
        try:
            from thiramai.runtime.sqlite_job_store import load_all_jobs

            sorted_jobs = sorted(
                load_all_jobs().values(),
                key=lambda r: float(r.get("created_ts") or 0),
                reverse=True,
            )
            for row in sorted_jobs:
                if int(row.get("organization_id") or 0) != oid:
                    continue
                if not privileged and int(row.get("user_id") or 0) != uid:
                    continue
                rows_out.append(
                    {
                        "id": row["id"],
                        "goal": row.get("goal"),
                        "status": display_status(row.get("status")),
                        "created_ts": row.get("created_ts"),
                        "finished_ts": row.get("finished_ts"),
                        "ok": row.get("ok"),
                        "clean_cycle": row.get("clean_cycle"),
                        "error": row.get("error"),
                        "progress_pct": row.get("progress_pct"),
                        "dispatch_mode": row.get("dispatch_mode"),
                        "user_id": row.get("user_id"),
                        "organization_id": row.get("organization_id"),
                    }
                )
                if len(rows_out) >= lim:
                    break
            return rows_out
        except Exception:
            pass
    with _jobs_lock:
        out: list[dict[str, Any]] = []
        for jid in list(_history):
            row = _jobs.get(jid)
            if not row:
                continue
            if int(row.get("organization_id") or 0) != oid:
                continue
            if not privileged and int(row.get("user_id") or 0) != uid:
                continue
            out.append(
                {
                    "id": row["id"],
                    "goal": row.get("goal"),
                    "status": display_status(row.get("status")),
                    "created_ts": row.get("created_ts"),
                    "finished_ts": row.get("finished_ts"),
                    "ok": row.get("ok"),
                    "clean_cycle": row.get("clean_cycle"),
                    "error": row.get("error"),
                    "progress_pct": row.get("progress_pct"),
                    "dispatch_mode": row.get("dispatch_mode"),
                    "user_id": row.get("user_id"),
                    "organization_id": row.get("organization_id"),
                }
            )
            if len(out) >= lim:
                break
        return out


def reset_stop_event_for_tests() -> None:
    global _executor_shutdown_done, _accepting_new_jobs
    _executor_shutdown_done = False
    _accepting_new_jobs = True
    with _jobs_lock:
        _jobs.clear()
        _history.clear()


def count_running_jobs() -> int:
    with _jobs_lock:
        return sum(1 for j in _jobs.values() if j.get("status") == "running")


def readiness_snapshot() -> dict[str, Any]:
    """Deep checks for /health/ready (SQLite goal store, queue depth, SQLite worker heartbeats)."""
    detail: dict[str, Any] = {
        "job_sqlite_enabled": bool(THIRAMAI_JOB_SQLITE),
        "sqlite": {"ok": True, "detail": "skipped"},
        "worker_queue_depth_by_status": {},
        "sqlite_workers_recent": [],
    }
    if not THIRAMAI_JOB_SQLITE:
        detail["sqlite"] = {"ok": True, "detail": "THIRAMAI_JOB_SQLITE off (jobs in-process only)"}
        return detail
    try:
        from thiramai.runtime.sqlite_job_store import sqlite_goal_queue_depth, sqlite_jobs_ping_ok

        ok_sql, msg_sql = sqlite_jobs_ping_ok()
        detail["sqlite"] = {"ok": ok_sql, "detail": msg_sql}
        detail["worker_queue_depth_by_status"] = sqlite_goal_queue_depth()
        ws = workers_snapshot(stale_after_sec=120.0)
        detail["sqlite_workers_recent"] = (ws.get("workers") or [])[:24]
    except Exception as exc:
        detail["sqlite"] = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
    return detail


def aggregate_metrics() -> dict[str, Any]:
    """Summary for Prometheus text export."""
    with _jobs_lock:
        total = len(_jobs)
        runn = sum(1 for j in _jobs.values() if j.get("status") == "running")
        failed = sum(1 for j in _jobs.values() if j.get("status") == "failed")
        intr = sum(1 for j in _jobs.values() if j.get("status") == "interrupted")
        comp = sum(1 for j in _jobs.values() if j.get("status") == "completed")
        ms_vals = [float(j.get("execution_ms") or 0) for j in _jobs.values() if j.get("execution_ms")]
    avg_ms = sum(ms_vals) / len(ms_vals) if ms_vals else 0.0
    return {
        "jobs_total_tracked": total,
        "jobs_running": runn,
        "jobs_failed": failed,
        "jobs_interrupted": intr,
        "jobs_completed": comp,
        "avg_execution_ms": round(avg_ms, 3),
    }
