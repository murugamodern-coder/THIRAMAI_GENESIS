"""Research worker — safe reads via ``execute_intent`` (snapshot); no external scrapes by default."""

from __future__ import annotations

from typing import Any

from core.observability import log_structured

_SAFE = frozenset({"read_inventory"})


def run_tasks(
    decisions: list[dict[str, Any]],
    context: dict[str, Any],
    *,
    auto_mode: bool,
    request_id: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from core.tool_executor import execute_intent

    oid = int(context.get("organization_id") or 0)
    taken: list[dict[str, Any]] = []
    suggestions: list[dict[str, Any]] = []

    ctx_exec = {
        "organization_id": oid,
        "actor_role_name": context.get("actor_role_name") or "owner",
        "user_id": context.get("user_id"),
        "role_level": context.get("role_level"),
        "user_message": "",
        "correlation_id": context.get("correlation_id") or request_id,
        "experience_source": "agent",
    }

    for d in decisions:
        if str(d.get("worker") or "") != "research":
            continue
        intent = d.get("intent")
        if intent is None:
            suggestions.append({**d, "_held": "suggestion_only_no_tool"})
            log_structured(
                "agent.worker.research_suggestion",
                request_id=request_id,
                organization_id=oid,
                decision_type=d.get("decision_type"),
            )
            continue
        intent_s = str(intent)
        if intent_s not in _SAFE:
            suggestions.append({**d, "_safety": "intent_not_allowed"})
            continue
        if not auto_mode:
            suggestions.append({**d, "_held": "auto_mode_off"})
            continue
        if oid <= 0:
            suggestions.append({**d, "_held": "missing_org"})
            continue

        intent_data: dict[str, Any] = {
            "intent": intent_s,
            "entity": d.get("entity") or "",
            "quantity": d.get("quantity"),
            "confidence": 1.0,
            "source": "research_worker",
            "read_mode": d.get("read_mode") or "snapshot",
        }
        out = execute_intent(intent_data, ctx_exec)
        taken.append({"decision": d, "result": out})
        log_structured(
            "agent.worker.research_action",
            request_id=request_id,
            organization_id=oid,
            intent=intent_s,
            ok=bool(out.get("ok")),
        )

    return taken, suggestions
