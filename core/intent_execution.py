"""
Bridge between brain ``ActionIntent`` (Pydantic) and dashboard natural-language command shapes.

Dashboard commands use a flat ``parsed`` dict (``action``, ``entity_name``, ``value``, ``numeric_value``, …)
from Groq or keyword fallbacks; brain responses use a discriminated ``action_intent``. Keep mappings here so
orchestrator, HTTP layers, and ``POST /dashboard/command/execute`` stay aligned.
"""

from __future__ import annotations

from typing import Any

from core.brain_output import (
    ActionIntent,
    ActionIntentNone,
    CreateInvoiceAction,
    OrderStockAction,
    SellStockAction,
    TriggerSolarResearchAction,
    UpdateStockAction,
)


def dashboard_action_for_intent(intent: ActionIntent) -> str | None:
    """Canonical dashboard ``action`` string if the intent maps to a registered NL command, else ``None``."""
    if isinstance(intent, ActionIntentNone):
        return None
    if isinstance(intent, UpdateStockAction):
        return "inventory_adjust"
    if isinstance(intent, OrderStockAction):
        return "inventory_adjust"
    if isinstance(intent, TriggerSolarResearchAction):
        return "trigger_solar_research"
    if isinstance(intent, (SellStockAction, CreateInvoiceAction)):
        return None
    return None


def parsed_dict_for_dashboard(intent: ActionIntent, *, rationale: str = "intent_execution_bridge") -> dict[str, Any]:
    """
    Build a ``parsed`` dict compatible with ``services.dashboard_command_executor`` handlers.

    Handlers expect keys: ``action``, ``entity_name``, ``value``, ``numeric_value``, ``confidence``, ``rationale``.
    """
    base = {
        "entity_name": "",
        "value": "",
        "numeric_value": None,
        "confidence": 1.0,
        "rationale": rationale,
    }
    if isinstance(intent, ActionIntentNone):
        return {**base, "action": "unknown"}
    if isinstance(intent, UpdateStockAction):
        return {
            **base,
            "action": "inventory_adjust",
            "entity_name": intent.sku_name.strip(),
            "value": (intent.location or "").strip(),
            "numeric_value": float(intent.quantity_delta),
        }
    if isinstance(intent, OrderStockAction):
        return {
            **base,
            "action": "inventory_adjust",
            "entity_name": intent.sku_name.strip(),
            "value": (intent.location or "").strip(),
            "numeric_value": float(intent.quantity),
            "rationale": f"{rationale}:order_stock_as_receipt",
        }
    if isinstance(intent, TriggerSolarResearchAction):
        return {
            **base,
            "action": "trigger_solar_research",
            "value": "force_refresh" if intent.force_refresh else "",
            "numeric_value": None,
        }
    if isinstance(intent, SellStockAction):
        return {**base, "action": "unknown", "rationale": "sell_stock_not_dashboard_nl"}
    if isinstance(intent, CreateInvoiceAction):
        return {**base, "action": "unknown", "rationale": "create_invoice_not_dashboard_nl"}
    return {**base, "action": "unknown"}
