"""Central execution engine for `/execute` API.

Flow:
1) detect intent
2) route module
3) execute action
4) return structured response
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import uuid

from services.brain_entry_guards import blocked_response_for_central_execute, global_halt_active
from services.intent_classifier import classify_intent
from services.modular_execution_services import (
    BuildService,
    BusinessService,
    MoneyService,
    PersonalService,
    ResearchService,
    ServiceExecutionContext,
)

IntentName = str


@dataclass(frozen=True)
class ExecutionContext:
    user_id: int
    organization_id: int
    role_name: str


def detect_intent(command: str) -> IntentName:
    return classify_intent(command)


def _resolve_contextual_command(command: str, context_messages: list[dict[str, Any]] | None) -> str:
    base = str(command or "").strip()
    if not base:
        return ""
    history = context_messages or []
    if not history:
        return base
    # Follow-up prompts like "do it now" are disambiguated using recent turns.
    if len(base) >= 24:
        return base
    recent = []
    for msg in history[-6:]:
        role = str(msg.get("role") or "").strip().lower()
        content = str(msg.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            recent.append(f"{role}: {content}")
    if not recent:
        return base
    return f"{' | '.join(recent)} | user: {base}"


_INTENT_SERVICES = {
    "personal": PersonalService(),
    "business": BusinessService(),
    "research": ResearchService(),
    "money": MoneyService(),
    "build": BuildService(),
}


def execute_command(
    command: str,
    ctx: ExecutionContext,
    context_messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    execution_id = f"exec_{uuid.uuid4().hex[:10]}"
    if global_halt_active():
        return blocked_response_for_central_execute(execution_id)
    contextual_command = _resolve_contextual_command(command, context_messages)
    intent = detect_intent(contextual_command)
    service = _INTENT_SERVICES.get(intent, ResearchService())
    steps: list[dict[str, str]] = [
        {
            "id": "s0",
            "label": f"Loaded conversation context ({len(context_messages or [])} messages)",
            "status": "done",
        },
        {"id": "s1", "label": "Understanding command", "status": "done"},
        {"id": "s2", "label": "Intent classified", "status": "done"},
        {"id": "s3", "label": "Resolve organization context", "status": "done"},
        {"id": "s4", "label": f"Routing to {intent} module", "status": "done"},
    ]
    out = service.execute(
        contextual_command,
        ServiceExecutionContext(
            user_id=ctx.user_id,
            organization_id=ctx.organization_id,
            role_name=ctx.role_name,
            conversation_context=context_messages or [],
        ),
    )
    service_steps = out.get("steps")
    if isinstance(service_steps, list):
        for idx, raw in enumerate(service_steps, start=1):
            if isinstance(raw, dict):
                step_status = str(raw.get("status") or "done").lower()
                if step_status not in {"pending", "running", "done", "error"}:
                    step_status = "done"
                steps.append(
                    {
                        "id": str(raw.get("id") or f"svc_{idx}"),
                        "label": str(raw.get("label") or f"Service step {idx}"),
                        "status": step_status,
                    }
                )
            elif isinstance(raw, str):
                steps.append({"id": f"svc_{idx}", "label": raw, "status": "done"})
    # Backward compatibility for older API consumers expecting "trading" label.
    if out.get("intent") == "money":
        out["intent"] = "trading"
    out["execution_id"] = execution_id
    out["steps"] = steps
    return out
