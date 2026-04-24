"""
Execution watchdog for stale action runs.

Detects long-running / long-awaiting-confirmation runs, marks watchdog state in run
meta, and routes each stale run through execution closure authority.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import ActionExecutionRun
from services.execution_closure_engine import handle_execution_closure
from services.auto_retry_engine import auto_retry_execution


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_dt(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v
    return None


def _last_touch(row: ActionExecutionRun) -> datetime:
    return _as_dt(row.updated_at) or _as_dt(row.created_at) or _now()


def _minutes_ago(dt: datetime) -> float:
    return max(0.0, (_now() - dt).total_seconds() / 60.0)


def run_execution_watchdog_scan(
    *,
    running_timeout_min: int = 15,
    awaiting_confirmation_timeout_min: int = 30,
    cooldown_min: int = 5,
    max_runs_per_scan: int = 100,
) -> dict[str, Any]:
    """
    Scan stale execution runs and route them through closure authority:
    - stale running -> mark ``stuck`` -> ``handle_execution_closure``
    - stale awaiting_confirmation -> mark ``needs_intervention`` -> ``handle_execution_closure``
    """
    factory = get_session_factory()
    if not factory:
        return {"ok": False, "error": "database_unavailable"}

    now = _now()
    cutoff_running = now - timedelta(minutes=max(1, int(running_timeout_min)))
    cutoff_awaiting = now - timedelta(minutes=max(1, int(awaiting_confirmation_timeout_min)))
    cooldown_delta = timedelta(minutes=max(1, int(cooldown_min)))

    actions: list[dict[str, Any]] = []
    with factory() as session:
        rows = session.execute(
            select(ActionExecutionRun)
            .where(ActionExecutionRun.status.in_(("running", "awaiting_confirmation")))
            .order_by(ActionExecutionRun.updated_at.asc())
            .limit(max(1, min(int(max_runs_per_scan), 1000)))
        ).scalars().all()

        for row in rows:
            rid = int(row.id)
            st = str(row.status or "").lower()
            touched = _last_touch(row)
            stale_running = st == "running" and touched <= cutoff_running
            stale_awaiting = st == "awaiting_confirmation" and touched <= cutoff_awaiting
            if not stale_running and not stale_awaiting:
                continue

            meta = dict(row.meta_json or {})
            wd_prev = meta.get("execution_watchdog") if isinstance(meta.get("execution_watchdog"), dict) else {}
            last_routed_raw = wd_prev.get("last_routed_at")
            last_routed: datetime | None = None
            if isinstance(last_routed_raw, str):
                try:
                    last_routed = datetime.fromisoformat(last_routed_raw.replace("Z", "+00:00"))
                except ValueError:
                    last_routed = None
            if last_routed is not None and (now - last_routed) < cooldown_delta:
                continue

            mark = "stuck" if stale_running else "needs_intervention"
            wd = {
                **wd_prev,
                "state": mark,
                "run_status_at_detection": st,
                "detected_at": now.isoformat(),
                "last_routed_at": now.isoformat(),
                "last_touch_at": touched.isoformat(),
                "stale_minutes": round(_minutes_ago(touched), 2),
                "counter": int(wd_prev.get("counter") or 0) + 1,
            }
            meta["execution_watchdog"] = wd
            row.meta_json = meta
            row.updated_at = now
            actions.append({"run_id": rid, "mark": mark})

        session.commit()

    routed: list[dict[str, Any]] = []
    for item in actions:
        rid = int(item["run_id"])
        mark = str(item["mark"])
        try:
            res = handle_execution_closure(rid)
            routed.append({"run_id": rid, "mark": mark, "route": "handle_execution_closure", "result": res})
        except Exception as exc:  # noqa: BLE001
            routed.append({"run_id": rid, "mark": mark, "ok": False, "error": str(exc)[:500]})

    return {
        "ok": True,
        "scanned_statuses": ["running", "awaiting_confirmation"],
        "timeouts_min": {
            "running": int(running_timeout_min),
            "awaiting_confirmation": int(awaiting_confirmation_timeout_min),
            "cooldown": int(cooldown_min),
        },
        "flagged_count": len(actions),
        "routed_count": len(routed),
        "routed": routed,
    }


def run_retry_job_drain(*, max_runs: int = 100) -> dict[str, Any]:
    """
    Drain durable retry jobs persisted in run.meta_json["retry_job"].

    Guarantee: each scheduled retry is executed or marked failed explicitly.
    """
    factory = get_session_factory()
    if not factory:
        return {"ok": False, "error": "database_unavailable"}
    now = _now()
    candidates: list[dict[str, Any]] = []
    with factory() as session:
        rows = session.execute(select(ActionExecutionRun).order_by(ActionExecutionRun.updated_at.asc()).limit(max(1, int(max_runs)))).scalars().all()
        for row in rows:
            meta = dict(row.meta_json or {})
            rj = meta.get("retry_job") if isinstance(meta.get("retry_job"), dict) else {}
            if str(rj.get("retry_status") or "") != "scheduled":
                continue
            not_before_raw = str(rj.get("next_attempt_not_before") or "")
            if not_before_raw:
                try:
                    not_before = datetime.fromisoformat(not_before_raw.replace("Z", "+00:00"))
                    if not_before > now:
                        continue
                except ValueError:
                    pass
            candidates.append({"run_id": int(row.id), "retry_steps": list(rj.get("retry_steps") or [])})
    executed: list[dict[str, Any]] = []
    for c in candidates:
        rid = int(c["run_id"])
        retry_steps = [x for x in c.get("retry_steps") or [] if isinstance(x, dict)]
        res = auto_retry_execution(rid, retry_steps=retry_steps)
        executed.append({"run_id": rid, "result": res})
    return {"ok": True, "scheduled_found": len(candidates), "executed_count": len(executed), "executed": executed}
