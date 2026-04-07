"""Revenue, business decision, growth, and scale engines (no DB for core logic)."""

from __future__ import annotations

from core.business_decision_engine import analyze_business_decisions
from core.growth_engine import detect_growth_ideas
from core.revenue_engine import analyze_revenue
from core.scale_engine import detect_scale_products


def test_analyze_revenue_missing_org():
    r = analyze_revenue({"organization_id": 0})
    assert r["ok"] is False
    assert r["weekly_trend"] == "unknown"


def test_business_decisions_no_sales_marketing():
    ctx = {
        "organization_id": 1,
        "request_id": "x",
        "_revenue_analysis": {
            "ok": True,
            "alerts": [{"code": "no_revenue_today", "level": "info"}],
        },
        "_tenant_state": {"dashboard": {"ok": True, "top_selling_products": []}, "low_stock": {"ok": True, "items": []}},
    }
    dec = analyze_business_decisions(ctx)
    assert any(d.get("decision") == "marketing_push" for d in dec)


def test_business_decisions_low_profit_price():
    ctx = {
        "organization_id": 1,
        "_revenue_analysis": {
            "ok": True,
            "today_revenue_inr": "100",
            "profit_estimate": {"estimated_gross_margin_inr_today": -5.0},
        },
        "_tenant_state": {},
    }
    dec = analyze_business_decisions(ctx)
    assert any(d.get("decision") == "increase_price" for d in dec)
    assert any(d.get("decision") == "reduce_cost" for d in dec)


def test_growth_new_product_idea():
    ctx = {
        "organization_id": 1,
        "_tenant_state": {
            "inventory_row_count": 10,
            "dashboard": {
                "ok": True,
                "top_selling_products": [{"sku_name": "Widget A", "quantity_sold": 9.0}],
            },
            "low_stock": {"ok": True, "items": [{"sku_name": "solar panel 100w", "quantity": 1.0}]},
            "notifications": {"items": []},
        },
    }
    ideas = detect_growth_ideas(ctx)
    assert any("solar" in (i.get("idea") or "").lower() for i in ideas)


def test_scale_saas_ideas():
    ctx = {
        "organization_id": 1,
        "_tenant_state": {
            "inventory_row_count": 3,
            "dashboard": {"ok": True, "revenue_inr": {"this_month": "500"}},
            "notifications": {"unread_count": 2, "items": [{}]},
            "low_stock": {"ok": True, "count": 1},
        },
    }
    prods = detect_scale_products(ctx)
    names = [p["product"] for p in prods]
    assert any("Billing" in n for n in names)
    assert any("Inventory" in n for n in names)
