"""AI business layer: prioritization, action plan, safe execution hooks."""

from __future__ import annotations

from unittest.mock import patch

from core.action_planner import build_action_plan
from core.decision_prioritizer import prioritize_decisions
from core.multi_agent_cycle import _execute_business_action_plan


def test_marketing_prioritized_among_mixed_decisions():
    decs = [
        {"decision": "restock_fast_items", "reason": "low", "entity": "a", "source": "x"},
        {"decision": "marketing_push", "reason": "no sales", "source": "x"},
    ]
    ranked = prioritize_decisions(decs, organization_id=0)
    keys = [r.get("decision") for r in ranked]
    assert keys[0] == "marketing_push"


def test_action_plan_restock_maps_to_add_inventory():
    decisions = [
        {
            "decision": "restock_fast_items",
            "entity": "soap",
            "reason": "fast",
            "source": "business_decision_engine",
            "priority_score": 0.9,
        }
    ]
    ctx = {
        "organization_id": 1,
        "_tenant_state": {
            "low_stock": {
                "ok": True,
                "threshold": 5,
                "items": [{"sku_name": "soap", "quantity": 1.0}],
            },
        },
    }
    plan = build_action_plan(decisions, ctx)
    assert any(s.get("intent") == "add_inventory" for s in plan)
    assert plan[0].get("entity") == "soap"


def test_marketing_is_suggestion_step():
    decisions = [{"decision": "marketing_push", "reason": "x", "source": "e", "priority_score": 0.8}]
    plan = build_action_plan(decisions, {"organization_id": 1})
    assert plan and plan[0].get("type") == "suggestion"
    assert plan[0].get("intent") is None


def test_business_plan_executes_restock_when_auto_mode():
    ctx = {
        "organization_id": 1,
        "actor_role_name": "owner",
        "auto_mode": True,
    }
    plan = [
        {
            "from_decision": "restock_fast_items",
            "decision_ref": {"decision": "restock_fast_items"},
            "intent": "add_inventory",
            "type": "execute",
            "entity": "soap",
            "quantity": 2.0,
            "priority": "high",
        }
    ]
    with patch("core.tool_executor.execute_intent") as ex:
        ex.return_value = {"ok": True, "message": "ok", "data": {}}
        with patch("core.multi_agent_cycle.track_results"):
            with patch("core.multi_agent_cycle.update_strategy_memory", return_value=0.7):
                taken, held, rt, su = _execute_business_action_plan(
                    plan, ctx, auto_mode=True, request_id="r1"
                )
    assert len(taken) == 1
    assert not held
    assert rt and su
    ex.assert_called_once()


def test_repeated_failure_lowers_priority_score():
    decs = [{"decision": "restock_fast_items", "reason": "r", "source": "s"}]
    with patch("core.strategy_memory.confidence_multiplier_for_decision", return_value=0.55):
        ranked = prioritize_decisions(decs, organization_id=1)
    assert ranked[0]["priority_score"] < ranked[0]["_priority_base"]
