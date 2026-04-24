"""Map ``brain_execute`` results to legacy API response shapes (no extra execution)."""

from __future__ import annotations

from typing import Any

from services.action_execution_engine import get_action_execution_run
from services.lifecycle_state import lifecycle_from_brain_fields


def brain_to_execute_response_dict(
    brain: dict[str, Any],
    *,
    conversation_id: int | None,
    command: str,
) -> dict[str, Any]:
    """Payload compatible with ``ExecuteResponse``."""
    res = brain.get("result") if isinstance(brain.get("result"), dict) else {}
    rid = res.get("run_id")
    intent = str(brain.get("intent") or "unknown")
    steps: list[dict[str, Any]] = []
    for i, s in enumerate(res.get("steps") or []):
        if not isinstance(s, dict):
            continue
        ok = s.get("ok")
        st = "done" if ok else "failed"
        if s.get("skipped"):
            st = "done"
        label = f"{s.get('phase') or ''}: {s.get('step_kind') or ''}".strip(": ").strip() or f"step_{i}"
        steps.append(
            {
                "id": str(s.get("step_order", i)),
                "label": label,
                "status": st if st in ("pending", "running", "done", "error", "failed") else "done",
                "step_order": s.get("step_order"),
                "result": s.get("result"),
            }
        )
    if not steps:
        bst = brain.get("status") or "failed"
        steps.append(
            {
                "id": "brain_0",
                "label": "brain_execute",
                "status": "done" if bst == "success" else "failed",
                "step_order": 0,
                "result": res,
            }
        )
    bst = brain.get("status") or "failed"
    outer_status = "success" if bst == "success" else "error"
    lifecycle_state = lifecycle_from_brain_fields(
        status=str(bst),
        result=(res if isinstance(res, dict) else {}),
        governor_decision=(brain.get("autonomy_governor_decision") if isinstance(brain.get("autonomy_governor_decision"), dict) else {}),
    )
    return {
        "type": "execution",
        "execution_id": f"brain_{rid}" if rid else "brain",
        "conversation_id": conversation_id,
        "mission_id": None,
        "intent": intent,
        "steps": steps,
        "result": {"brain": brain, "command": command},
        "status": outer_status,
        "lifecycle_state": lifecycle_state,
    }


def brain_to_action_run_payload(brain: dict[str, Any], *, user_id: int) -> dict[str, Any]:
    """Shape similar to ``create_action_execution_run`` / ``get_action_execution_run``."""
    res = brain.get("result") if isinstance(brain.get("result"), dict) else {}
    rid = int(res.get("run_id") or 0)
    if rid <= 0:
        return {
            "ok": False,
            "deprecated_forwarded_to_brain": True,
            "brain": brain,
        }
    row = get_action_execution_run(run_id=rid, user_id=int(user_id))
    if row is None:
        return {"ok": False, "deprecated_forwarded_to_brain": True, "brain": brain}
    return {**row, "deprecated_forwarded_to_brain": True, "brain": brain}


def brain_to_agent_command_envelope(
    brain: dict[str, Any],
    *,
    correlation_id: str,
    command: str,
) -> dict[str, Any]:
    """Rough compatibility with ``create_plan_from_command`` consumer fields."""
    res = brain.get("result") if isinstance(brain.get("result"), dict) else {}
    rid = res.get("run_id")
    ok = (brain.get("status") or "") == "success"
    task_id = f"brain_{rid}" if rid else f"brain_{correlation_id[:12]}"
    return {
        "ok": ok,
        "routing": "brain_execute",
        "routed_to": "brain",
        "response": str(res.get("error") or res.get("stopped") or brain.get("status") or ""),
        "suggested_route": "/brain/execute",
        "os_key": "brain",
        "task_id": task_id,
        "requires_approval": False,
        "deprecated_forwarded_to_brain": True,
        "correlation_id": correlation_id,
        "command": command,
        "brain": brain,
    }
