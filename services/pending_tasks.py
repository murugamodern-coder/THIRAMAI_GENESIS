"""
Pending human work: HITL approvals plus open EPA agenda tasks (vault).
"""

from __future__ import annotations

from typing import Any

import executive_core


def list_pending_hitl(*, organization_id: int) -> list[dict[str, Any]]:
    """Pending ``approvals`` rows for the tenant (empty if DB unavailable)."""
    try:
        from services import approval_store

        return approval_store.list_pending(organization_id=int(organization_id))
    except Exception:
        return []


def list_open_agenda_tasks(*, limit: int = 30) -> list[dict[str, Any]]:
    """Undone tasks from ``vault/agenda_state.json``."""
    data = executive_core.load_agenda_state()
    tasks = [t for t in (data.get("tasks") or []) if isinstance(t, dict) and not t.get("done")]
    return tasks[: int(limit)]
