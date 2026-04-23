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


_INTENT_SERVICES = {
    "personal": PersonalService(),
    "business": BusinessService(),
    "research": ResearchService(),
    "money": MoneyService(),
    "build": BuildService(),
}


def execute_command(command: str, ctx: ExecutionContext) -> dict[str, Any]:
    intent = detect_intent(command)
    service = _INTENT_SERVICES.get(intent, ResearchService())
    out = service.execute(
        command,
        ServiceExecutionContext(
            user_id=ctx.user_id,
            organization_id=ctx.organization_id,
            role_name=ctx.role_name,
        ),
    )
    # Backward compatibility for older API consumers expecting "trading" label.
    if out.get("intent") == "money":
        out["intent"] = "trading"
    return out
