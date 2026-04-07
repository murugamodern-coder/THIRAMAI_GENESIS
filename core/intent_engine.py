"""
Production intent resolution for inventory-style operator commands.

Order: heuristics (``core.sale_intent_heuristic``) → optional Groq dashboard parse → normalized intent dict.
"""

from __future__ import annotations

from typing import Any, Literal

IntentName = Literal["sell_inventory", "add_inventory", "read_inventory", "unknown"]

def _looks_like_read_inventory(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    phrases = (
        "show inventory",
        "list inventory",
        "display inventory",
        "get inventory",
        "see inventory",
        "list stock",
        "show stock",
        "inventory status",
        "stock status",
        "inventory snapshot",
        "stock levels",
        "what's in stock",
        "what is in stock",
        "current stock",
        "how much stock",
    )
    return any(p in t for p in phrases)


def _empty_intent(*, source: Literal["heuristic", "llm", "none"] = "none") -> dict[str, Any]:
    return {
        "intent": "unknown",
        "entity": "",
        "quantity": None,
        "confidence": 0.0,
        "source": source,
    }


def _map_dashboard_action_to_intent(parsed: dict[str, Any]) -> dict[str, Any] | None:
    """Map ``_groq_extract_structured`` shape to engine intents (non-unknown actions only)."""
    action = str(parsed.get("action") or "").strip().lower()
    entity = str(parsed.get("entity_name") or "").strip()
    value = str(parsed.get("value") or "").strip()
    nv = parsed.get("numeric_value")
    conf = float(parsed.get("confidence") or 0.0)

    if action == "inventory_low_stock":
        return {
            "intent": "read_inventory",
            "entity": "",
            "quantity": None,
            "confidence": max(conf, 0.75),
            "source": "llm",
            "read_mode": "low_stock",
        }

    if action == "inventory_adjust":
        sku = entity or value
        if not sku:
            return None
        try:
            q = float(nv) if nv is not None else float("nan")
        except (TypeError, ValueError):
            return None
        if q != q:  # NaN
            return None
        return {
            "intent": "add_inventory",
            "entity": sku,
            "quantity": q,
            "confidence": max(conf, 0.7),
            "source": "llm",
        }

    return None


def resolve_intent(user_input: str, *, skip_llm: bool = False) -> dict[str, Any]:
    """
    Resolve natural language to a structured intent.

    Returns:
        ``intent`` — sell_inventory | add_inventory | read_inventory | unknown
        ``entity`` — SKU / product phrase (may be empty for read_inventory)
        ``quantity`` — numeric amount when applicable (signed allowed for add_inventory / adjustments)
        ``confidence`` — 0..1
        ``source`` — heuristic | llm | none

    Extra keys (optional): ``read_mode`` (e.g. low_stock), ``location`` (str).
    """
    text = (user_input or "").strip()
    if not text:
        return _empty_intent()

    from core.sale_intent_heuristic import (
        parsed_sell_intent_from_message,
        parsed_update_stock_intent_from_message,
    )

    sell = parsed_sell_intent_from_message(text)
    if sell is not None:
        return {
            "intent": "sell_inventory",
            "entity": sell.sku_name.strip(),
            "quantity": float(sell.quantity),
            "confidence": 1.0,
            "source": "heuristic",
            "location": (sell.location or "").strip(),
        }

    upd = parsed_update_stock_intent_from_message(text)
    if upd is not None:
        return {
            "intent": "add_inventory",
            "entity": upd.sku_name.strip(),
            "quantity": float(upd.quantity_delta),
            "confidence": 1.0,
            "source": "heuristic",
            "location": (upd.location or "").strip(),
        }

    if _looks_like_read_inventory(text):
        return {
            "intent": "read_inventory",
            "entity": "",
            "quantity": None,
            "confidence": 0.95,
            "source": "heuristic",
            "read_mode": "snapshot",
        }

    if not skip_llm:
        try:
            from services.dashboard_command_executor import _groq_extract_structured

            parsed = _groq_extract_structured(text)
        except RuntimeError:
            parsed = None
        if isinstance(parsed, dict):
            mapped = _map_dashboard_action_to_intent(parsed)
            if mapped is not None:
                return mapped

    return _empty_intent(source="heuristic" if skip_llm else "none")
