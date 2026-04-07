"""
Lightweight parsing when the LLM returns ``action_intent: none`` but the user clearly asked for ops.

Sell: "Sell 2 units of Item A", "sell 3 items pvc pipe".
Stock add/remove: "add 20 pvc pipe", "remove 5 units of soap".
Solar DPR: "run solar research" → ``TriggerSolarResearchAction`` (orchestrator runs Tavily bundle).
"""

from __future__ import annotations

import re

from core.brain_output import SellStockAction, TriggerSolarResearchAction, UpdateStockAction

_SELL_RE = re.compile(
    r"(?is)\b(?:sell|sold|sale of)\s+"
    r"(\d+)\s+"
    r"(?:(?:units?|items?|pcs?)\s+(?:of\s+)?)?"
    r"([^\n.!?]+?)"
    r"(?:\.|$|!|\?|\n)",
)

_STOCK_ADD_RE = re.compile(
    r"(?is)\b(?:add|receive|restock|stock\s+up|increase\s+stock|update\s+stock)\s+"
    r"(\d+)\s+"
    r"(?:(?:units?|items?|pcs?)\s+(?:of\s+)?)?"
    r"([^\n.!?]+?)"
    r"(?:\.|$|!|\?|\n)",
)

_STOCK_REMOVE_RE = re.compile(
    r"(?is)\b(?:remove|deduct|subtract)\s+"
    r"(\d+)\s+"
    r"(?:(?:units?|items?|pcs?)\s+(?:of\s+)?)?"
    r"([^\n.!?]+?)"
    r"(?:\.|$|!|\?|\n)",
)


def early_retail_sell_quantity_veto_message(user_message: str) -> str | None:
    """
    If the user clearly asks to sell a fractional amount, zero, or negative quantity,
    return a short business-facing message (no LLM / no execution). Otherwise ``None``.
    """
    text = (user_message or "").strip()
    if not text:
        return None
    m_neg = re.search(
        r"(?is)\b(?:sell|sold|sale of)\s+-\s*(\d+(?:\.\d+)?)\s*(?:(?:units?|items?)\s+(?:of\s+)?)?",
        text,
    )
    if m_neg:
        return (
            "**Cannot process sale:** Negative quantities are not valid. "
            "Use a positive whole number of units to sell."
        )
    m_frac = re.search(
        r"(?is)\b(?:sell|sold|sale of)\s+(\d+\.\d+)\s*(?:(?:units?|items?|pcs?)\s+(?:of\s+)?)?",
        text,
    )
    if m_frac:
        try:
            val = float(m_frac.group(1))
        except ValueError:
            return None
        if val != float(int(val)):
            return (
                "**Cannot process sale:** Only **whole units** can be sold. "
                "Fractional quantities (for example 0.5 units) are not supported."
            )
    m_zero = re.search(
        r"(?is)\b(?:sell|sold|sale of)\s+0+(?:\.0+)?\s+(?:(?:units?|items?)\s+of\s+)",
        text,
    )
    if m_zero:
        return "**Cannot process sale:** Quantity must be at least **1** whole unit."
    return None


def parsed_sell_intent_from_message(user_message: str) -> SellStockAction | None:
    """Return ``SellStockAction`` if the message matches a simple sell pattern; else ``None``."""
    text = (user_message or "").strip()
    if not text:
        return None
    m = _SELL_RE.search(text)
    if not m:
        return None
    try:
        q = int(m.group(1), 10)
    except ValueError:
        return None
    sku = (m.group(2) or "").strip().strip("\"'")
    if q <= 0 or len(sku) < 1:
        return None
    return SellStockAction(sku_name=sku, quantity=float(q), location="")


def parsed_update_stock_intent_from_message(user_message: str) -> UpdateStockAction | None:
    """Positive delta for add/restock phrases; negative for remove/deduct."""
    text = (user_message or "").strip()
    if not text:
        return None
    m = _STOCK_ADD_RE.search(text)
    if m:
        try:
            q = int(m.group(1), 10)
        except ValueError:
            return None
        sku = (m.group(2) or "").strip().strip("\"'")
        if q <= 0 or len(sku) < 1:
            return None
        return UpdateStockAction(sku_name=sku, quantity_delta=float(q), location="")
    m = _STOCK_REMOVE_RE.search(text)
    if m:
        try:
            q = int(m.group(1), 10)
        except ValueError:
            return None
        sku = (m.group(2) or "").strip().strip("\"'")
        if q <= 0 or len(sku) < 1:
            return None
        return UpdateStockAction(sku_name=sku, quantity_delta=float(-q), location="")
    return None


def parsed_solar_research_intent_from_message(user_message: str) -> TriggerSolarResearchAction | None:
    """Detect explicit solar / DPR market-research asks (orchestrator fills narrative from Tavily)."""
    tl = (user_message or "").strip().lower()
    if not tl:
        return None
    needles = (
        "solar research",
        "run solar",
        "solar dpr",
        "dpr research",
        "market research on solar",
        "solar market research",
        "refresh solar",
        "solar market",
        "tavily solar",
        "run dpr",
    )
    if not any(n in tl for n in needles):
        return None
    force = bool(
        re.search(r"\b(force\s+refresh|force-refresh|hard\s+refresh|bypass\s+cache)\b", tl)
    ) or ("refresh" in tl and "solar" in tl)
    return TriggerSolarResearchAction(force_refresh=force)
