"""
Structured brain output: narrative (user-facing Markdown) + action_intent (machine-routable).

Validated with Pydantic before returning to HTTP clients. Raw model text is parsed from JSON
(optionally inside ```json fences); invalid JSON falls back to narrative = raw text, kind = none.
"""

from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal, Union

EmpireUxMode = Literal["default", "nominal_silence"]

from pydantic import BaseModel, Field, TypeAdapter, ValidationError, field_validator


class ActionIntentNone(BaseModel):
    """No executable system action suggested."""

    kind: Literal["none"] = "none"


class CreateInvoiceAction(BaseModel):
    """Parameters aligned with POST /assets/invoice (billing route)."""

    kind: Literal["create_invoice"] = "create_invoice"
    length: float = Field(..., gt=0, description="Pipe length (m)")
    grade: str = Field(..., min_length=1, description="Material grade e.g. HDPE PE100")
    weight: float = Field(..., gt=0, description="Weight kg")
    rate: float = Field(..., gt=0, description="INR per kg")
    buyer: str = Field(default="Buyer", min_length=1)
    buyer_address: str = ""
    invoice_no: str = ""
    invoice_date: str = ""
    gst: float = Field(default=18.0, ge=0)
    seller: str = Field(default="Your legal business name", min_length=1)
    seller_address: str = ""
    seller_gstin: str = ""


class OrderStockAction(BaseModel):
    """Suggested replenishment — map to inventory / procurement flows on the client."""

    kind: Literal["order_stock"] = "order_stock"
    sku_name: str = Field(..., min_length=1)
    quantity: float = Field(..., gt=0)
    location: str = ""
    notes: str = ""


class UpdateStockAction(BaseModel):
    """Adjust on-hand quantity in PostgreSQL ``inventory`` (Stage 5 / execution engine)."""

    kind: Literal["update_stock"] = "update_stock"
    sku_name: str = Field(..., min_length=1)
    quantity_delta: float = Field(
        ...,
        description="Positive adds stock, negative removes (same org boundary as billing deduction).",
    )
    location: str = ""


class SellStockAction(BaseModel):
    """Sell N units of a SKU: check stock, deduct, record a ``bills`` row (retail / POS)."""

    kind: Literal["sell_stock"] = "sell_stock"
    sku_name: str = Field(..., min_length=1)
    quantity: float = Field(..., gt=0, description="Whole units sold (no fractions)")
    location: str = ""

    @field_validator("quantity")
    @classmethod
    def whole_units_only(cls, v: float) -> float:
        if v != int(v):
            raise ValueError(
                "quantity must be a positive whole number (fractional unit sales are not supported)"
            )
        return float(int(v))


class TriggerSolarResearchAction(BaseModel):
    """
    Solar DPR market research (Tavily bundle). Fulfilled inline in the orchestrator — not queued for HITL.
    """

    kind: Literal["trigger_solar_research"] = "trigger_solar_research"
    force_refresh: bool = False


ActionIntent = Annotated[
    Union[
        CreateInvoiceAction,
        OrderStockAction,
        UpdateStockAction,
        SellStockAction,
        TriggerSolarResearchAction,
        ActionIntentNone,
    ],
    Field(discriminator="kind"),
]

_action_intent_adapter: TypeAdapter[ActionIntent] = TypeAdapter(ActionIntent)


def normalize_action_intent_kind(raw: dict[str, Any]) -> dict[str, Any]:
    """Map uppercase / legacy AI labels to discriminator values (e.g. UPDATE_STOCK → update_stock)."""
    if not isinstance(raw, dict):
        return {}
    out = dict(raw)
    k = str(out.get("kind") or "").strip()
    upper = k.upper().replace("-", "_")
    aliases = {
        "UPDATE_STOCK": "update_stock",
        "ORDER_STOCK": "order_stock",
        "CREATE_INVOICE": "create_invoice",
        "SELL_STOCK": "sell_stock",
        "TRIGGER_SOLAR_RESEARCH": "trigger_solar_research",
        "SOLAR_RESEARCH": "trigger_solar_research",
        "NONE": "none",
    }
    if upper in aliases:
        out["kind"] = aliases[upper]
    return out


def parse_action_intent_dict(raw: dict[str, Any]) -> ActionIntent:
    """Validate a loose JSON ``action_intent`` object after normalizing ``kind``."""
    return _action_intent_adapter.validate_python(normalize_action_intent_kind(raw))


class BrainStructuredResponse(BaseModel):
    """Validated shape returned by run_brain after council / DPR."""

    narrative: str = Field(..., min_length=1, description="Markdown brief for the user")
    action_intent: ActionIntent
    empire_ux: EmpireUxMode = Field(
        default="default",
        description="Empire Governance: nominal_silence = exception-only UX (no user-facing chatter).",
    )


def _extract_json_object(text: str) -> dict | None:
    t = (text or "").strip()
    if not t:
        return None
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", t, re.DOTALL)
    if m:
        blob = m.group(1).strip()
        try:
            out = json.loads(blob)
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
                chunk = t[start : i + 1]
                try:
                    out = json.loads(chunk)
                    return out if isinstance(out, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def _fallback_narrative(raw: str) -> str:
    s = (raw or "").strip()
    return s if s else "(Empty response.)"


def parse_and_validate_brain_output(raw: str) -> tuple[BrainStructuredResponse, bool]:
    """
    Parse JSON from model output and validate. Returns (model, parse_ok).
    If JSON is missing or invalid, narrative is the raw text (or a safe default) and action_intent is none.
    """
    data = _extract_json_object(raw)
    if data is None:
        return (
            BrainStructuredResponse(
                narrative=_fallback_narrative(raw),
                action_intent=ActionIntentNone(),
            ),
            False,
        )
    try:
        narrative = data.get("narrative")
        if not isinstance(narrative, str) or not narrative.strip():
            raise ValueError("narrative must be a non-empty string")
        intent_raw = data.get("action_intent")
        if intent_raw is None:
            intent: ActionIntent = ActionIntentNone()
        elif isinstance(intent_raw, dict):
            intent = parse_action_intent_dict(intent_raw)
        else:
            raise ValueError("action_intent must be an object or omitted")
        return (
            BrainStructuredResponse(
                narrative=narrative.strip(),
                action_intent=intent,
            ),
            True,
        )
    except (ValidationError, ValueError, TypeError):
        return (
            BrainStructuredResponse(
                narrative=_fallback_narrative(raw),
                action_intent=ActionIntentNone(),
            ),
            False,
        )


def wrap_markdown_as_response(markdown: str) -> BrainStructuredResponse:
    """Programmatic wrap when the pipeline did not emit JSON (e.g. industrial DPR, stitched fallback)."""
    return BrainStructuredResponse(
        narrative=_fallback_narrative(markdown),
        action_intent=ActionIntentNone(),
    )
