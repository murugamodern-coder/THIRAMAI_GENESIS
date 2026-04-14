"""Week 1 FIX 1: single Jarvis router entrypoint (route_jarvis_query)."""

from __future__ import annotations

from services.jarvis_router import (
    classify_query,
    merge_route_tool_specs,
    route_jarvis_query,
    route_query,
    select_model_for_category,
)
from services.jarvis_agent_service import TOOL_SPECS


def test_route_jarvis_query_matches_merge_alias():
    msg = "What is my GST invoice status for this month?"
    a = route_jarvis_query(msg, TOOL_SPECS)
    b = merge_route_tool_specs(msg, TOOL_SPECS)
    assert a == b


def test_classify_stock_vs_inventory_disambiguation():
    assert classify_query("nifty rsi breakout") == "stock"
    assert classify_query("low stock on SKU reorder") == "business"


def test_select_model_non_empty():
    for cat in ("stock", "research", "business", "personal"):
        m = select_model_for_category(cat)  # type: ignore[arg-type]
        assert isinstance(m, str) and len(m) > 2


def test_route_query_includes_tool_names():
    r = route_query("record sale today")
    assert r["category"] == "business"
    assert "record_sale" in r["tool_names_set"]
