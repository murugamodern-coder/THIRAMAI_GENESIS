"""Entry: run LangGraph swarm and append blackboard notes to ``shared_core``."""

from __future__ import annotations

import os

from core.observability import log_structured
from core.sovereign_journal import record_cot_step
from core.swarm.blackboard import SwarmState
from core.swarm.graph import run_swarm


def orchestrator_swarm_enabled() -> bool:
    return (os.getenv("THIRAMAI_ORCHESTRATOR_SWARM") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def augment_shared_core_with_swarm(
    shared_core: str,
    *,
    user_message: str,
    organization_id: int,
    request_id: str,
    user_role_level: int,
    billing_paused: bool,
    actor_role_name: str | None = None,
) -> str:
    if not orchestrator_swarm_enabled():
        return shared_core
    max_retries = 2
    try:
        max_retries = max(0, min(5, int((os.getenv("THIRAMAI_SWARM_MAX_RETRIES") or "2").strip())))
    except ValueError:
        max_retries = 2

    initial: SwarmState = {
        "user_message": user_message,
        "organization_id": int(organization_id),
        "request_id": request_id,
        "user_role_level": int(user_role_level),
        "billing_paused": bool(billing_paused),
        "actor_role_name": actor_role_name,
        "max_retries": max_retries,
        "retry_count": 0,
    }
    try:
        final = run_swarm(initial)
    except Exception as exc:
        log_structured(
            "swarm.pipeline_failed",
            request_id=request_id,
            error=f"{type(exc).__name__}: {exc}"[:500],
        )
        return shared_core
    notes = (final.get("swarm_notes") or "").strip()
    if not notes:
        return shared_core
    log_structured("swarm.pipeline_ok", request_id=request_id, notes_chars=len(notes))
    record_cot_step(
        agent="swarm",
        phase="synthesis",
        detail=f"notes_chars={len(notes)} retries={final.get('retry_count')}",
        organization_id=int(organization_id),
        trace_id=request_id,
    )
    return shared_core + "\n\n## Swarm synthesis (shared blackboard)\n\n" + notes
