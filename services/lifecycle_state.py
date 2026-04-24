"""
Canonical execution lifecycle state mapping.

Global lifecycle states:
- assist
- blocked
- running
- retrying
- completed
- failed
- cancelled
"""

from __future__ import annotations

from typing import Any

LIFECYCLE_ASSIST = "assist"
LIFECYCLE_BLOCKED = "blocked"
LIFECYCLE_RUNNING = "running"
LIFECYCLE_RETRYING = "retrying"
LIFECYCLE_COMPLETED = "completed"
LIFECYCLE_FAILED = "failed"
LIFECYCLE_CANCELLED = "cancelled"

_ALLOWED_NEXT: dict[str, set[str]] = {
    LIFECYCLE_ASSIST: set(),
    LIFECYCLE_BLOCKED: set(),
    LIFECYCLE_RUNNING: {LIFECYCLE_RETRYING, LIFECYCLE_COMPLETED, LIFECYCLE_FAILED, LIFECYCLE_CANCELLED},
    LIFECYCLE_RETRYING: {LIFECYCLE_RUNNING, LIFECYCLE_FAILED},
    LIFECYCLE_FAILED: set(),
    LIFECYCLE_COMPLETED: set(),
    LIFECYCLE_CANCELLED: set(),
}


def lifecycle_from_brain_fields(
    *,
    status: str | None,
    result: dict[str, Any] | None = None,
    governor_decision: dict[str, Any] | None = None,
) -> str:
    res = result if isinstance(result, dict) else {}
    gov = governor_decision if isinstance(governor_decision, dict) else {}
    st = str(status or "").lower().strip()

    if gov and not bool(gov.get("allow_execute", True)):
        return LIFECYCLE_ASSIST
    if bool(res.get("assist_only")):
        return LIFECYCLE_ASSIST
    if bool(res.get("blocked")):
        return LIFECYCLE_BLOCKED
    if st == "success":
        return LIFECYCLE_COMPLETED
    if st == "partial":
        return LIFECYCLE_RETRYING
    if st == "failed":
        return LIFECYCLE_FAILED
    if st == "cancelled":
        return LIFECYCLE_CANCELLED
    if st == "running":
        return LIFECYCLE_RUNNING
    return LIFECYCLE_RUNNING


def lifecycle_from_action_run(
    *,
    run_status: str | None,
    meta_json: dict[str, Any] | None = None,
) -> str:
    st = str(run_status or "").lower().strip()
    meta = meta_json if isinstance(meta_json, dict) else {}
    closure = meta.get("execution_closure") if isinstance(meta.get("execution_closure"), dict) else {}
    closure_final = str(closure.get("final_status") or "").lower().strip()
    if st == "cancelled":
        return LIFECYCLE_CANCELLED
    if st == "completed":
        return LIFECYCLE_COMPLETED
    if st == "failed":
        if closure_final == "retry_needed":
            return LIFECYCLE_RETRYING
        return LIFECYCLE_FAILED
    if closure_final == "retry_needed":
        return LIFECYCLE_RETRYING
    if st == "awaiting_confirmation":
        return LIFECYCLE_BLOCKED
    if st in ("planned", "running"):
        return LIFECYCLE_RUNNING
    return LIFECYCLE_RUNNING


def lifecycle_from_closure_final_status(final_status: str | None) -> str:
    st = str(final_status or "").lower().strip()
    if st == "retry_needed":
        return LIFECYCLE_RETRYING
    if st == "completed":
        return LIFECYCLE_COMPLETED
    if st == "failed":
        return LIFECYCLE_FAILED
    return LIFECYCLE_RUNNING


def lifecycle_from_real_world_state(
    *,
    state: str | None,
    e2e: dict[str, Any] | None = None,
) -> str:
    st = str(state or "").lower().strip()
    e = e2e if isinstance(e2e, dict) else {}
    if st == "completed":
        return LIFECYCLE_COMPLETED
    if st == "failed":
        return LIFECYCLE_FAILED
    if st == "cancelled":
        return LIFECYCLE_CANCELLED
    if st == "in_progress" and bool(e.get("closure_pending")):
        return LIFECYCLE_BLOCKED
    if st in ("initiated", "in_progress"):
        return LIFECYCLE_RUNNING
    return LIFECYCLE_RUNNING


def transition_lifecycle_state(
    *,
    meta_json: dict[str, Any] | None,
    next_state: str,
    transition_name: str,
) -> tuple[bool, dict[str, Any], str]:
    """
    Enforce strict lifecycle transition table and update transition observability fields.
    Returns: (allowed, updated_meta, current_state)
    """
    meta = dict(meta_json or {})
    life = meta.get("lifecycle") if isinstance(meta.get("lifecycle"), dict) else {}
    current = str(life.get("state") or LIFECYCLE_RUNNING).strip().lower()
    nxt = str(next_state or "").strip().lower()
    if nxt not in _ALLOWED_NEXT:
        return False, meta, current
    if current == nxt:
        life["state"] = nxt
        life["last_transition"] = str(transition_name or f"{current}->{nxt}")
        meta["lifecycle"] = life
        return True, meta, current
    if nxt not in _ALLOWED_NEXT.get(current, set()):
        return False, meta, current
    life["state"] = nxt
    life["last_transition"] = str(transition_name or f"{current}->{nxt}")
    meta["lifecycle"] = life
    return True, meta, current

