"""
Base class for THIRAMAI multi-agent managers and workers.

All agents are **advisory** unless a caller enables ``auto_mode`` and routes actions through
``tool_executor.execute_intent`` with an explicit allow-list (see workers).
"""

from __future__ import annotations

import os
from typing import Any

from core.observability import log_structured


def multi_agent_enabled() -> bool:
    """Opt-in multi-agent pass from the orchestrator brain (default off)."""
    return (os.getenv("THIRAMAI_MULTI_AGENT") or "").strip().lower() in ("1", "true", "yes", "on")


def log_agent_experience(
    *,
    agent_name: str,
    decisions: list[dict[str, Any]],
    organization_id: int,
    request_id: str | None = None,
) -> None:
    """Append one experience row per decision for audit / learning."""
    if int(organization_id) <= 0:
        return
    try:
        from services.experience_buffer import record_experience

        for d in decisions[:32]:
            record_experience(
                source="agent",
                action=f"{agent_name}.decide",
                result={"decision": d},
                success=True,
                meta={
                    "agent": agent_name,
                    "organization_id": int(organization_id),
                    "request_id": request_id,
                },
                tags=["multi_agent", f"org:{int(organization_id)}"],
            )
    except Exception:
        pass


class BaseAgent:
    def __init__(self, name: str, role: str) -> None:
        self.name = name
        self.role = role

    def observe(self, context: dict[str, Any]) -> dict[str, Any]:
        """Optional domain-specific observations (default: none)."""
        return {}

    def decide(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        """Return structured decisions (may be routed to workers by ``worker`` field)."""
        return []

    def act(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        """Default: workers perform acts; managers rarely override."""
        return []

    def emit_log(
        self,
        event: str,
        *,
        request_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        payload = {"agent": self.name, "role": self.role}
        if extra:
            payload.update(extra)
        log_structured(
            f"agent.{event}",
            request_id=request_id,
            **{k: v for k, v in payload.items() if v is not None},
        )

    def log_decisions(
        self,
        decisions: list[dict[str, Any]],
        context: dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> None:
        oid = int(context.get("organization_id") or 0)
        self.emit_log(
            "decide",
            request_id=request_id,
            extra={"decision_count": len(decisions)},
        )
        log_agent_experience(
            agent_name=self.name,
            decisions=decisions,
            organization_id=oid,
            request_id=request_id,
        )
