"""Unit tests for orchestrator brain + safe autonomy (mocked I/O)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from core.orchestrator_brain import run_orchestrator_brain


@pytest.fixture
def base_ctx():
    return {
        "organization_id": 1,
        "actor_role_name": "admin",
        "user_id": 1,
        "correlation_id": "c-test",
        "role_level": 1,
        "auto_mode": False,
        "trigger": "user",
    }


def test_sell_resolves_to_execute(base_ctx):
    with patch("core.autonomy_engine.evaluate_autonomy", return_value=[]):
        with patch("core.tool_executor.execute_intent") as ex:
            ex.return_value = {
                "ok": True,
                "status": "success",
                "action": "sell_inventory",
                "message": "Sold 5 soap",
                "data": {},
            }
            out = run_orchestrator_brain("Sell 5 soap", base_ctx, request_id="r1")
    assert out["handled"] is True
    assert out["mode"] == "execute"
    assert out["action"] == "sell_inventory"
    assert out["autonomous"] is False
    assert "soap" in out["message"].lower() or "sold" in out["message"].lower()
    ex.assert_called_once()


def test_show_inventory_execute_read(base_ctx):
    with patch("core.autonomy_engine.evaluate_autonomy", return_value=[]):
        with patch("core.tool_executor.execute_intent") as ex:
            ex.return_value = {
                "ok": True,
                "status": "success",
                "action": "read_inventory",
                "message": "Inventory snapshot: 0 row(s) (tenant-scoped, capped).",
                "data": {"count": 0},
            }
            out = run_orchestrator_brain("Show inventory", base_ctx, request_id="r2")
    assert out["handled"] is True
    assert out["mode"] == "execute"
    assert out["action"] == "read_inventory"
    ex.assert_called_once()


def test_question_falls_back_to_council(base_ctx):
    with patch("core.autonomy_engine.evaluate_autonomy", return_value=[]):
        with patch("core.tool_executor.execute_intent") as ex:
            out = run_orchestrator_brain("What is our strategy for Q4?", base_ctx, request_id="r3")
    assert out["handled"] is False
    assert out["mode"] == "respond"
    ex.assert_not_called()


def test_low_stock_suggestion_logged_not_executed_user_trigger(base_ctx):
    suggestions = [
        {
            "intent": "add_inventory",
            "reason": "low_stock",
            "entity": "soap",
            "quantity": 3.0,
            "priority": "high",
            "reference": {},
        }
    ]
    with patch("core.autonomy_engine.evaluate_autonomy", return_value=suggestions):
        with patch("core.tool_executor.execute_intent") as ex:
            ex.return_value = {"ok": True, "action": "read_inventory", "message": "ok", "data": {}}
            out = run_orchestrator_brain("Show inventory", base_ctx, request_id="r4")
    assert out["handled"] is True
    assert ex.call_count == 1
    call_intent = ex.call_args[0][0]
    assert call_intent.get("intent") == "read_inventory"


def test_auto_mode_off_system_no_execute(base_ctx):
    base_ctx["trigger"] = "system"
    base_ctx["auto_mode"] = False
    suggestions = [
        {"intent": "add_inventory", "reason": "low_stock", "entity": "x", "quantity": 1.0, "priority": "high"}
    ]
    with patch("core.autonomy_engine.evaluate_autonomy", return_value=suggestions):
        with patch("core.tool_executor.execute_intent") as ex:
            out = run_orchestrator_brain("", base_ctx, request_id="r5")
    assert out["handled"] is True
    ex.assert_not_called()
    assert "suggestion" in out["brain_response"].narrative.lower() or "operator" in out[
        "brain_response"
    ].narrative.lower()


def test_auto_mode_on_system_executes_safe_intents(base_ctx):
    base_ctx["trigger"] = "system"
    base_ctx["auto_mode"] = True
    suggestions = [
        {"intent": "add_inventory", "reason": "low_stock", "entity": "x", "quantity": 2.0, "priority": "high"}
    ]
    with patch("core.autonomy_engine.evaluate_autonomy", return_value=suggestions):
        with patch("core.tool_executor.execute_intent") as ex:
            ex.return_value = {"ok": True, "action": "add_inventory", "message": "Added", "data": {}}
            out = run_orchestrator_brain("", base_ctx, request_id="r6")
    assert out["handled"] is True
    ex.assert_called_once()
    assert out["autonomous"] is True


def test_autonomy_never_sells(base_ctx):
    base_ctx["trigger"] = "system"
    base_ctx["auto_mode"] = True
    suggestions = [
        {"intent": "sell_inventory", "reason": "bad", "entity": "x", "quantity": 1.0, "priority": "high"}
    ]
    with patch("core.autonomy_engine.evaluate_autonomy", return_value=suggestions):
        with patch("core.tool_executor.execute_intent") as ex:
            out = run_orchestrator_brain("", base_ctx, request_id="r7")
    assert out["handled"] is True
    ex.assert_not_called()


def test_evaluate_autonomy_low_stock_shape():
    from core.autonomy_engine import evaluate_autonomy

    fake_items = [{"sku_name": "SKU1", "quantity": 1.0, "location": "A"}]
    with patch(
        "services.analytics_service.list_low_stock_alerts_sync",
        return_value={"ok": True, "items": fake_items, "threshold": 5},
    ):
        with patch("workers.alert_system.list_active_alerts_for_organization", return_value={"items": []}):
            got = evaluate_autonomy({"organization_id": 9})
    assert len(got) >= 1
    assert got[0]["intent"] == "add_inventory"
    assert got[0]["reason"] == "low_stock"
