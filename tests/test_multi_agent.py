"""Multi-agent managers, workers, and SaaS factory (mocked DB/tool paths)."""

from __future__ import annotations

from unittest.mock import patch

from agents.compliance_manager import ComplianceManager
from agents.growth_manager import GrowthManager
from agents.inventory_manager import InventoryManager
from core.orchestrator_brain import run_multi_agent_cycle
from core.saas_factory import run_saas_factory


def test_inventory_manager_low_stock():
    m = InventoryManager()
    ctx = {
        "organization_id": 1,
        "_tenant_state": {
            "organization_id": 1,
            "low_stock": {
                "ok": True,
                "count": 1,
                "threshold": 5,
                "items": [{"sku_name": "soap", "quantity": 1.0, "location": ""}],
            },
        },
    }
    dec = m.decide(ctx)
    assert len(dec) >= 1
    assert dec[0]["manager"] == "inventory_manager"
    assert dec[0]["worker"] == "inventory"
    assert dec[0]["intent"] == "add_inventory"
    assert dec[0]["reason"] == "low_stock_restock"


def test_compliance_manager_gst():
    c = ComplianceManager()
    ctx = {
        "organization_id": 1,
        "_tenant_state": {
            "notifications": {
                "items": [{"id": 9, "kind": "gst_reminder", "title": "GSTR-1", "body": "due"}],
            },
        },
    }
    dec = c.decide(ctx)
    assert any(d.get("decision_type") == "gst_compliance_review" for d in dec)
    assert any(d.get("worker") == "research" for d in dec)


def test_growth_manager_no_sales():
    g = GrowthManager()
    ctx = {
        "organization_id": 1,
        "_tenant_state": {
            "organization_id": 1,
            "inventory_row_count": 3,
            "dashboard": {
                "ok": True,
                "revenue_inr": {"today": "0", "this_month": "500"},
                "top_selling_products": [{"sku_name": "a", "quantity_sold": 1.0}],
            },
        },
    }
    with patch("time.gmtime") as gm:
        gm.return_value = type("T", (), {"tm_hour": 14})()
        dec = g.decide(ctx)
    assert any(d.get("decision_type") == "no_sales_growth_review" for d in dec)


def test_inventory_worker_blocks_sell():
    from agents.workers import inventory_worker

    bad = [
        {
            "worker": "inventory",
            "intent": "sell_inventory",
            "entity": "x",
            "quantity": 1,
        }
    ]
    with patch("core.tool_executor.execute_intent") as ex:
        t, s = inventory_worker.run_tasks(
            bad, {"organization_id": 1, "auto_mode": True}, auto_mode=True, request_id="r"
        )
    assert not t
    assert s
    ex.assert_not_called()


def test_multi_agent_cycle_shape(monkeypatch):
    monkeypatch.setenv("THIRAMAI_AUTONOMOUS_NO_SALES_MIN_HOUR_UTC", "0")
    state = {
        "organization_id": 7,
        "low_stock": {
            "ok": True,
            "count": 1,
            "threshold": 5,
            "items": [{"sku_name": "soap", "quantity": 1.0, "location": "", "gst_rate_percent": None}],
        },
        "dashboard": {
            "ok": True,
            "revenue_inr": {"today": "0", "this_month": "1"},
            "top_selling_products": [{"sku_name": "soap", "quantity_sold": 1.0}],
        },
        "notifications": {"ok": True, "items": [{"id": 1, "kind": "gst", "title": "GST", "body": "x"}]},
        "recent_experiences": [],
        "inventory_row_count": 2,
    }
    fake_rev = {
        "ok": True,
        "organization_id": 7,
        "today_revenue_inr": "0",
        "weekly_revenue_inr": "1",
        "monthly_revenue_inr": "100",
        "weekly_trend": "soft_vs_monthly_run_rate",
        "profit_estimate": {"estimated_gross_margin_inr_today": -10.0, "disclaimer": "test"},
        "alerts": [{"code": "no_revenue_today"}],
    }
    with patch("core.multi_agent_cycle.observe_tenant_state", return_value=state):
        with patch("core.multi_agent_cycle.analyze_revenue", return_value=fake_rev):
            with patch("core.tool_executor.execute_intent") as ex:
                ex.return_value = {"ok": True, "action": "read_inventory", "message": "ok", "data": {}}
                with patch("services.experience_buffer.record_experience"):
                    out = run_multi_agent_cycle(
                        {"organization_id": 7, "auto_mode": False, "request_id": "t1"}
                    )
    assert out["status"] == "ai_business_cycle_complete"
    assert "agents" in out and "decisions" in out
    assert any(d.get("manager") == "inventory_manager" for d in out["decisions"])
    assert any("GST" in (p.get("product") or "") for p in out.get("saas_opportunities", []))
    assert out.get("revenue_analysis") == fake_rev
    assert "top_decisions" in out and "action_plan" in out
    kinds = [s.get("kind") for s in out.get("suggestions", [])]
    assert "business_decision" in kinds
    assert "growth_idea" in kinds


def test_saas_factory_suggestions():
    ctx = {
        "_tenant_state": {
            "organization_id": 1,
            "low_stock": {
                "ok": True,
                "items": [{"sku_name": "a", "quantity": 1, "gst_rate_percent": None, "hsn_code": ""}],
            },
            "notifications": {"items": []},
            "dashboard": {"ok": False},
            "inventory_row_count": 1,
        }
    }
    prods = run_saas_factory(ctx)
    names = [p["product"] for p in prods]
    assert any("GST" in n for n in names)


def test_run_multi_agent_cycle_brain_export():
    """``orchestrator_brain.run_multi_agent_cycle`` delegates to pipeline."""
    assert callable(run_multi_agent_cycle)
