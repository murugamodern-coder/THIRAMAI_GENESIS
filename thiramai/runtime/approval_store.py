"""Human-in-the-loop: block high-risk tasks until approved via API."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

_store_lock = threading.Lock()
_pending: dict[str, dict[str, Any]] = {}
_events: dict[str, threading.Event] = {}


def enqueue_high_risk_task(
    *,
    task: dict[str, Any],
    cycle_id: int,
    task_id: str,
    goal: str,
) -> str:
    aid = uuid.uuid4().hex
    with _store_lock:
        _pending[aid] = {
            "approval_id": aid,
            "status": "pending",
            "created_ts": time.time(),
            "cycle_id": cycle_id,
            "task_id": task_id,
            "goal": goal,
            "task_summary": {
                "type": task.get("type"),
                "description": task.get("description"),
                "command": task.get("command"),
                "risk_level": task.get("risk_level"),
            },
        }
        _events[aid] = threading.Event()
    return aid


def wait_for_approval(approval_id: str, *, timeout_sec: float | None) -> dict[str, Any]:
    evt = _events.get(approval_id)
    if evt is None:
        return {"ok": False, "reason": "unknown_approval_id"}
    t = 86400.0
    if timeout_sec is not None and float(timeout_sec) > 0:
        t = float(timeout_sec)
    ok = evt.wait(timeout=t)
    with _store_lock:
        row = _pending.get(approval_id)
        if row and row.get("status") == "approved":
            return {"ok": True, "approved_by": row.get("approved_by"), "approved_ts": row.get("approved_ts")}
        if row and row.get("status") == "rejected":
            return {"ok": False, "reason": row.get("reject_reason") or "rejected"}
    if not ok:
        return {"ok": False, "reason": "approval_timeout"}
    return {"ok": False, "reason": "unknown_state"}


def approve(approval_id: str, *, approved_by: str = "api") -> dict[str, Any]:
    with _store_lock:
        row = _pending.get(approval_id)
        if not row:
            return {"ok": False, "error": "not_found"}
        row["status"] = "approved"
        row["approved_ts"] = time.time()
        row["approved_by"] = approved_by
        evt = _events.get(approval_id)
    if evt:
        evt.set()
    return {"ok": True, "approval_id": approval_id}


def reject(approval_id: str, *, reason: str = "") -> dict[str, Any]:
    with _store_lock:
        row = _pending.get(approval_id)
        if not row:
            return {"ok": False, "error": "not_found"}
        row["status"] = "rejected"
        row["reject_reason"] = reason or "rejected"
        evt = _events.get(approval_id)
    if evt:
        evt.set()
    return {"ok": True, "approval_id": approval_id}


def list_pending() -> list[dict[str, Any]]:
    with _store_lock:
        return [dict(v) for v in _pending.values() if v.get("status") == "pending"]


def clear_completed_for_tests() -> None:
    with _store_lock:
        for k in list(_pending.keys()):
            if _pending[k].get("status") != "pending":
                del _pending[k]
                _events.pop(k, None)
