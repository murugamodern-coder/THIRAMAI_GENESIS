"""
Jarvis query router: classify intent → tool subset + Groq model (fast vs smart).

Only the relevant tools are passed to the LLM (not all 25).
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Literal

_log = logging.getLogger("thiramai.jarvis_router")

QueryCategory = Literal["business", "research", "stock", "personal"]

# --- Tool sets (must match registered tool names) ---
PERSONAL_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "create_task",
        "log_expense",
        "schedule_meeting",
        "get_today_brief",
        "set_health_log",
        "get_upcoming_emis",
        "create_habit",
    }
)

BUSINESS_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "get_business_snapshot",
        "search_inventory",
        "create_invoice",
        "add_stock",
        "record_sale",
        "add_business_expense",
        "get_business_pnl",
        "add_farmer",
        "update_subsidy_status",
        "log_production",
        "mark_attendance",
        "get_stock_status",
        "get_pending_payments",
        "generate_poster_content",
        "draft_business_email",
        "get_today_brief",
    }
)

RESEARCH_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "research_topic",
        "research_market",
        "find_govt_schemes",
        "generate_dpr",
        "analyze_competitors",
        "get_today_brief",
    }
)

STOCK_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "analyze_stock_opportunity",
        "get_today_brief",
    }
)


def _stock_market_hit(q: str) -> bool:
    """Match equity keywords without substring false positives (e.g. ``nse`` inside ``expense``)."""
    phrases = ("share price", "nifty 50", "bank nifty")
    if any(p in q for p in phrases):
        return True
    tokens = (
        "nse",
        "bse",
        "sensex",
        "nifty",
        "equity",
        "intraday",
        "macd",
        "rsi",
        "breakout",
    )
    for t in tokens:
        if re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", q, re.I):
            return True
    return False


def classify_query(message: str) -> QueryCategory:
    """Single primary bucket for routing."""
    raw = message or ""
    q = raw.lower()

    inv_words = ("inventory", "sku", "stock level", "reorder", "warehouse", "சரக்கு", "பொருள்")
    biz_inventory = any(w in raw for w in inv_words) or any(w in q for w in ("low stock", "add stock", "purchase order"))

    stock_mkt = _stock_market_hit(q)
    if stock_mkt and not biz_inventory:
        return "stock"

    research = any(
        k in q
        for k in (
            "scheme",
            "schemes",
            "govt",
            "government",
            "subsidy application",
            "pm-kisan",
            "msme scheme",
            "research ",
            "market size",
            "competitor",
            "dpr",
        )
    )
    if research:
        return "research"

    business = any(
        k in q
        for k in (
            "invoice",
            "gst",
            "bill",
            "farmer",
            "subsidy case",
            "production",
            "machine",
            "attendance",
            "staff",
            "profit",
            "p&l",
            "pnl",
            "operational expense",
            "purchase order",
            "supplier",
            "payment due",
            "receivable",
            "poster",
            "email draft",
            "quotation",
        )
    ) or biz_inventory
    if business:
        return "business"

    return "personal"


def tool_names_for_category(category: QueryCategory) -> frozenset[str]:
    if category == "stock":
        return STOCK_TOOL_NAMES
    if category == "research":
        return RESEARCH_TOOL_NAMES
    if category == "business":
        return BUSINESS_TOOL_NAMES
    return PERSONAL_TOOL_NAMES


def select_model_for_category(category: QueryCategory) -> str:
    fast = (os.getenv("GROQ_FAST_MODEL") or "llama-3.1-8b-instant").strip()
    smart = (
        os.getenv("GROQ_SMART_MODEL") or os.getenv("GROQ_AGENT_MODEL") or os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile"
    ).strip()
    if category in ("stock", "research"):
        return smart
    return fast


def filter_tool_specs(all_specs: list[dict[str, Any]], allowed_names: frozenset[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for spec in all_specs:
        if not isinstance(spec, dict):
            continue
        fn = spec.get("function") or {}
        name = fn.get("name")
        if name in allowed_names:
            out.append(spec)
    if not out:
        _log.warning("filter_tool_specs: empty subset, falling back to personal tools")
        return filter_tool_specs(all_specs, PERSONAL_TOOL_NAMES)
    return out


def route_query(message: str) -> dict[str, Any]:
    """
    Full router output for Jarvis.

    Returns:
        category, model, tool_names (sorted list), tool_specs (filtered).
    """
    category = classify_query(message.strip())
    names = tool_names_for_category(category)
    model = select_model_for_category(category)
    return {
        "category": category,
        "model": model,
        "tool_names": sorted(names),
        # tool_specs filled by caller with master TOOL_SPECS
        "tool_names_set": names,
    }


def merge_route_tool_specs(message: str, master_tool_specs: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], QueryCategory]:
    """Returns (model, specs_subset, category)."""
    r = route_query(message)
    specs = filter_tool_specs(master_tool_specs, r["tool_names_set"])
    return r["model"], specs, r["category"]
