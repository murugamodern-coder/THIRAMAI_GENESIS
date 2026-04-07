"""
Phase 3 — Groq JSON-only decision pass (single round, no Tavily).
"""

from __future__ import annotations

import json
import os
from typing import Any

from core.decision_schema import (
    AIDecision,
    decision_is_safe,
    parse_and_validate_decision,
)
from core.swarm.llm import groq_chat
from services.context_engine import build_business_context_snapshot


_DECISION_SYSTEM = """You are THIRAMAI Decision Engine for a manufacturing / ERP tenant.

You MUST respond with exactly ONE JSON object and NOTHING else (no markdown, no prose).
Schema:
{
  "action": "<one of: noop, reorder_stock, create_purchase_order, mark_invoice_paid, send_alert, send_payment_reminder, record_stock_movement, create_task>",
  "entity": "<short label e.g. inventory_item, invoice, supplier>",
  "data": { },
  "priority": "<low|medium|high>",
  "requires_approval": <true|false>,
  "rationale": "<one sentence why>"
}

Rules:
- Prefer requires_approval=true for money movement, purchase orders, or large stock changes.
- Use noop when no concrete system action is needed.
- data must include concrete ids/fields the backend can use (e.g. sku_name, quantity, invoice_id, inventory_item_id).
- Use context.inventory_alerts and financial_summary to prioritize.
"""


def run_decision_engine_sync(
    user_message: str,
    organization_id: int,
    *,
    actor_role_name: str | None = None,
    user_id: int | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """
    Build business context → Groq JSON decision → validate.

    Returns a dict with keys: ok, context_snapshot, decision (dict or null), errors, raw_model.
    """
    _ = actor_role_name, user_id, correlation_id  # reserved for logging / future RBAC hints in prompt
    ctx = build_business_context_snapshot(int(organization_id))
    payload = {"context": ctx, "user_query": (user_message or "").strip()}
    user_block = json.dumps(payload, default=str)[:24000]

    if not (os.getenv("GROQ_API_KEY") or "").strip():
        return {
            "ok": False,
            "error": "GROQ_API_KEY is not configured",
            "context_snapshot": ctx,
            "decision": None,
        }

    try:
        raw = groq_chat(
            system=_DECISION_SYSTEM,
            user=user_block,
            temperature=0.1,
            max_tokens=2048,
        )
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "context_snapshot": ctx,
            "decision": None,
            "raw_model": "",
        }

    dec, verr = parse_and_validate_decision(raw)
    out: dict[str, Any] = {
        "ok": verr is None and dec is not None,
        "context_snapshot": ctx,
        "decision": dec.model_dump(mode="json") if dec else None,
        "validation_error": verr,
        "raw_model": raw[:8000],
    }
    if dec is None:
        return out

    safe_ok, safe_err = decision_is_safe(dec)
    out["safety_ok"] = safe_ok
    out["safety_error"] = safe_err
    out["ok"] = bool(safe_ok and verr is None)
    if not safe_ok:
        out["ok"] = False
    return out


def decision_from_dict(d: dict[str, Any]) -> AIDecision | None:
    """Validate an already-parsed decision dict (tests / admin)."""
    dec, err = parse_and_validate_decision(d)
    if err or dec is None:
        return None
    return dec
