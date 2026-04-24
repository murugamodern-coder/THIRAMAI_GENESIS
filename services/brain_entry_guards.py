"""
Shared preflight for user-facing entry points (orchestrator, /execute) so kill-switch and
future cross-cutting gates apply consistently. Action execution path already checks halt in
``action_execution_engine``.
"""

from __future__ import annotations

from typing import Any


def global_halt_active() -> bool:
    try:
        from services.autonomy_safety_layer import global_autonomy_halted

        return bool(global_autonomy_halted())
    except Exception:  # noqa: BLE001
        return False


def blocked_response_for_central_execute(execution_id: str) -> dict[str, Any]:
    """Shape compatible with ``services.central_execution_engine.execute_command`` consumers."""
    return {
        "type": "execution",
        "intent": "governance",
        "status": "error",
        "result": {"ok": False, "error": "global_autonomy_halt"},
        "execution_id": execution_id,
        "steps": [
            {
                "id": "halt",
                "label": "System-wide autonomous execution is halted (operator kill switch).",
                "status": "error",
            },
        ],
    }
