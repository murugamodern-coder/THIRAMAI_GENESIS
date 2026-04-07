"""Central hooks to record tool executions into long-term vector memory."""

from __future__ import annotations

from typing import Any

from services import ltm_chroma


def record_inventory_sell_execution(
    *,
    organization_id: int,
    prompt_context: str,
    sku_name: str,
    quantity: float,
    location: str,
    result: dict[str, Any],
    correlation_id: str | None = None,
) -> None:
    """After ``inventory.sell_stock`` path completes (success, business error, or PROPOSE)."""
    action = {
        "sku_name": sku_name,
        "quantity": quantity,
        "location": (location or "").strip(),
    }
    ok = bool(result.get("ok"))
    err_parts = []
    if not ok:
        if result.get("policy") == "PROPOSE":
            err_parts.append("policy:PROPOSE")
        err_parts.append(str(result.get("error") or result.get("detail") or result.get("message") or ""))
    ltm_chroma.record_tool_execution(
        organization_id=int(organization_id),
        prompt_context=prompt_context or "",
        tool_id="inventory.sell_stock",
        action=action,
        outcome_ok=ok,
        error_message=" | ".join(p for p in err_parts if p).strip(),
        correlation_id=correlation_id,
    )
