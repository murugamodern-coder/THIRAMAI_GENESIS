"""
Phase 3 — strict schema for AI decision JSON (validate before execution or HITL storage).
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

# Actions the executor may handle (extend with matching code in action_executor).
ALLOWED_ACTIONS: frozenset[str] = frozenset(
    {
        "noop",
        "reorder_stock",
        "create_purchase_order",
        "mark_invoice_paid",
        "send_alert",
        "send_payment_reminder",
        "record_stock_movement",
        "create_task",
    }
)

Priority = Literal["low", "medium", "high"]


class AIDecision(BaseModel):
    """Structured decision emitted by the decision brain (JSON-only)."""

    action: str = Field(..., min_length=1, max_length=64)
    entity: str = Field(default="", max_length=64)
    data: dict[str, Any] = Field(default_factory=dict)
    priority: Priority = "medium"
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional model confidence (0..1). Used by autonomy layer for auto-actions.",
    )
    requires_approval: bool = True
    rationale: str = Field(default="", max_length=4000)

    @field_validator("action")
    @classmethod
    def action_allowlist(cls, v: str) -> str:
        a = (v or "").strip().lower()
        if a not in ALLOWED_ACTIONS:
            raise ValueError(f"action not allowed: {v!r}; must be one of {sorted(ALLOWED_ACTIONS)}")
        return a

    def model_dump_json_safe(self) -> str:
        return self.model_dump_json()


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Parse first JSON object from model output (supports ```json fences)."""
    t = (text or "").strip()
    if not t:
        return None
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", t, re.DOTALL)
    if m:
        try:
            out = json.loads(m.group(1).strip())
            return out if isinstance(out, dict) else None
        except json.JSONDecodeError:
            return None
    start = t.find("{")
    if start < 0:
        return None
    depth = 0
    for i, c in enumerate(t[start:], start=start):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    out = json.loads(t[start : i + 1])
                    return out if isinstance(out, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def normalize_decision_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Map common aliases to canonical ``ALLOWED_ACTIONS`` names."""
    out = dict(data)
    if "data" not in out and "payload" in out:
        out["data"] = out.get("payload") or {}
    if "action" in out:
        a = str(out["action"]).strip().lower().replace("-", "_")
        aliases = {
            "order_stock": "reorder_stock",
            "stock_reorder": "reorder_stock",
            "replenish": "reorder_stock",
            "pay_invoice": "mark_invoice_paid",
            "invoice_payment": "mark_invoice_paid",
            "purchase_order": "create_purchase_order",
            "po": "create_purchase_order",
            "po_create": "create_purchase_order",
            "alert": "send_alert",
            "notify": "send_alert",
            "payment_reminder": "send_payment_reminder",
            "remind_payment": "send_payment_reminder",
            "movement": "record_stock_movement",
            "stock_movement": "record_stock_movement",
            "none": "noop",
            "no_op": "noop",
            "idle": "noop",
            "production_log": "create_task",
            "log_production": "create_task",
            "create_production_log": "create_task",
        }
        out["action"] = aliases.get(a, a)
    return out


def parse_and_validate_decision(raw: str | dict[str, Any]) -> tuple[AIDecision | None, str | None]:
    """
    Returns (decision, error_message).
    Accepts raw model string or already-parsed dict.
    """
    if isinstance(raw, dict):
        data = raw
    else:
        data = extract_json_object(str(raw))
        if data is None:
            return None, "model output did not contain valid JSON object"

    data = normalize_decision_dict(data if isinstance(data, dict) else {})
    if "action" not in data:
        return None, "missing action"

    try:
        return AIDecision.model_validate(data), None
    except ValidationError as e:
        return None, str(e.errors())[:2000]


def decision_is_safe(d: AIDecision) -> tuple[bool, str | None]:
    """
    Extra guardrails beyond Pydantic (numeric bounds, required keys per action).
    """
    if d.action == "noop":
        return True, None
    if d.action == "reorder_stock":
        # PO path: same shape as create_purchase_order
        if d.data.get("supplier_id") and isinstance(d.data.get("lines"), list) and len(d.data.get("lines") or []) > 0:
            return True, None
        sku = str(d.data.get("sku_name") or "").strip()
        qty = d.data.get("quantity")
        if not sku:
            return False, "reorder_stock requires data.sku_name (or supplier_id+lines for PO)"
        try:
            q = float(qty)
        except (TypeError, ValueError):
            return False, "reorder_stock requires numeric data.quantity"
        if q <= 0 or q > 1_000_000:
            return False, "quantity out of allowed range"
        return True, None
    if d.action == "mark_invoice_paid":
        if not d.data.get("invoice_id"):
            return False, "mark_invoice_paid requires data.invoice_id"
        try:
            amt = float(d.data.get("amount_inr", 0))
        except (TypeError, ValueError):
            return False, "mark_invoice_paid requires numeric data.amount_inr"
        if amt <= 0:
            return False, "amount_inr must be positive"
        return True, None
    if d.action == "send_alert":
        if not str(d.data.get("message") or "").strip():
            return False, "send_alert requires data.message"
        return True, None
    if d.action == "send_payment_reminder":
        if not d.data.get("invoice_id"):
            return False, "send_payment_reminder requires data.invoice_id"
        if not str(d.data.get("message") or "").strip():
            return False, "send_payment_reminder requires data.message"
        return True, None
    if d.action == "create_purchase_order":
        if not d.data.get("supplier_id"):
            return False, "create_purchase_order requires data.supplier_id"
        lines = d.data.get("lines")
        if not isinstance(lines, list) or len(lines) == 0:
            return False, "create_purchase_order requires data.lines (non-empty list)"
        return True, None
    if d.action == "record_stock_movement":
        if not d.data.get("inventory_item_id"):
            return False, "record_stock_movement requires data.inventory_item_id"
        try:
            float(d.data.get("quantity_delta", 0))
        except (TypeError, ValueError):
            return False, "record_stock_movement requires numeric data.quantity_delta"
        return True, None
    if d.action == "create_task":
        if not d.data.get("asset_id"):
            return False, "create_task requires data.asset_id"
        return True, None
    return False, "action failed safety check"
