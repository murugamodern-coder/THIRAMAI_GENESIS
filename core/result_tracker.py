"""
Audit trail for AI business layer tool outcomes (experience buffer; no side effects on money).
"""

from __future__ import annotations

from typing import Any

from core.observability import log_structured


def track_results(
    action: dict[str, Any],
    result: dict[str, Any],
    *,
    organization_id: int = 0,
    request_id: str | None = None,
) -> None:
    """
    Record success/failure and a light-weight ``impact_hint`` for analytics (not accounting truth).
    """
    oid = int(organization_id)
    if oid <= 0:
        return

    ok = bool(result.get("ok"))
    intent = action.get("intent")
    impact_hint = "unknown"
    if intent == "add_inventory":
        impact_hint = "stock_adjusted" if ok else "stock_adjust_failed"
    elif intent == "read_inventory":
        impact_hint = "snapshot_taken" if ok else "read_failed"

    try:
        from services.experience_buffer import record_experience

        record_experience(
            source="result_tracker",
            action=str(intent or action.get("from_decision") or "unknown"),
            result={
                "ok": ok,
                "impact_hint": impact_hint,
                "from_decision": action.get("from_decision"),
                "tool_message": str(result.get("message") or "")[:2000],
                "tool_data_keys": list((result.get("data") or {}).keys())
                if isinstance(result.get("data"), dict)
                else [],
            },
            success=ok,
            meta={
                "organization_id": oid,
                "request_id": request_id,
                "from_decision": action.get("from_decision"),
            },
            tags=["ai_business_cycle", f"org:{oid}"],
        )
    except Exception:
        pass

    log_structured(
        "result_tracker.recorded",
        request_id=request_id,
        organization_id=oid,
        intent=intent,
        ok=ok,
        impact_hint=impact_hint,
    )
