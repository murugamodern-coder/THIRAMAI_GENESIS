"""Notification worker — audit-only routing for finance/compliance (no financial tools)."""

from __future__ import annotations

from typing import Any

from core.observability import log_structured


def run_tasks(
    decisions: list[dict[str, Any]],
    context: dict[str, Any],
    *,
    auto_mode: bool,
    request_id: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Never calls ``sell_inventory`` or payment flows. Emits structured logs + suggestion records.
    """
    oid = int(context.get("organization_id") or 0)
    taken: list[dict[str, Any]] = []
    suggestions: list[dict[str, Any]] = []

    for d in decisions:
        if str(d.get("worker") or "") != "notification":
            continue
        log_structured(
            "agent.worker.notification_decision",
            request_id=request_id,
            organization_id=oid,
            decision_type=d.get("decision_type"),
            manager=d.get("manager"),
            reason=d.get("reason"),
        )
        row = {
            "decision": d,
            "result": {
                "ok": True,
                "channel": "log_only",
                "detail": "Operator should review in-app notifications / dashboard",
            },
        }
        taken.append(row)

    return taken, suggestions
