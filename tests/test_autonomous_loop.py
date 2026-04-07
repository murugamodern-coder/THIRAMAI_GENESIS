"""Tests for autonomous cycle (mocked observe + tools)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from core.autonomous_loop import (
    autonomous_mode_enabled,
    run_autonomous_cycle,
    _safety_partition,
)
from core.autonomous_scheduler import _auto_execute_flag, _organization_ids


def _minimal_state(oid: int = 1) -> dict:
    return {
        "organization_id": oid,
        "ts": 0.0,
        "low_stock": {"ok": True, "count": 0, "items": [], "threshold": 5},
        "dashboard": {
            "ok": True,
            "revenue_inr": {"today": "100", "this_month": "100"},
            "top_selling_products": [{"sku_name": "a"}],
        },
        "notifications": {"ok": True, "items": []},
        "recent_experiences": [],
        "inventory_row_count": 1,
    }


def test_cycle_complete_shape():
    with patch("core.autonomous_loop._observe", return_value=_minimal_state(1)):
        with patch("core.autonomy_engine.evaluate_autonomy", return_value=[]):
            with patch("core.tool_executor.execute_intent") as ex:
                with patch("core.autonomous_loop._log_experience"):
                    out = run_autonomous_cycle({"organization_id": 1, "auto_mode": False})
    assert out["status"] == "cycle_complete"
    assert "actions_taken" in out
    assert "suggestions" in out
    assert out["learning_logged"] is True
    ex.assert_not_called()


def test_auto_mode_executes_safe_intent_only():
    sug = [
        {
            "intent": "add_inventory",
            "entity": "soap",
            "quantity": 2.0,
            "reason": "low_stock",
            "priority": "high",
            "kind": "tool",
        }
    ]
    with patch("core.autonomous_loop._observe", return_value=_minimal_state(1)):
        with patch("core.autonomy_engine.evaluate_autonomy", return_value=sug):
            with patch("core.tool_executor.execute_intent") as ex:
                ex.return_value = {"ok": True, "action": "add_inventory", "message": "ok", "data": {}}
                with patch("core.autonomous_loop._log_experience"):
                    out = run_autonomous_cycle({"organization_id": 1, "auto_mode": True})
    assert len(out["actions_taken"]) == 1
    assert out["actions_taken"][0]["ok"] is True
    ex.assert_called_once()


def test_sell_intent_never_executed():
    bad = [
        {
            "intent": "sell_inventory",
            "entity": "soap",
            "quantity": 1.0,
            "reason": "x",
            "kind": "tool",
        }
    ]
    with patch("core.autonomous_loop._observe", return_value=_minimal_state(1)):
        with patch("core.autonomy_engine.evaluate_autonomy", return_value=bad):
            with patch("core.tool_executor.execute_intent") as ex:
                with patch("core.autonomous_loop._log_experience"):
                    out = run_autonomous_cycle({"organization_id": 1, "auto_mode": True})
    ex.assert_not_called()
    assert any(s.get("intent") == "sell_inventory" for s in out["suggestions"])


def test_safety_partition():
    acts = [
        {"intent": "read_inventory", "kind": "tool"},
        {"intent": "sell_inventory", "kind": "tool"},
        {"intent": "notify_operator", "kind": "notify"},
    ]
    run, sug = _safety_partition(acts)
    assert len(run) == 1
    assert run[0]["intent"] == "read_inventory"
    assert len(sug) == 2


def test_autonomous_mode_env_default_off(monkeypatch):
    monkeypatch.delenv("THIRAMAI_AUTONOMOUS_MODE", raising=False)
    assert autonomous_mode_enabled() is False


def test_scheduler_org_ids_from_env(monkeypatch):
    monkeypatch.setenv("THIRAMAI_AUTONOMOUS_ORG_IDS", "2,3")
    assert _organization_ids() == [2, 3]
    monkeypatch.delenv("THIRAMAI_AUTONOMOUS_ORG_IDS", raising=False)
    monkeypatch.setenv("THIRAMAI_AUTONOMOUS_ORG_ID", "7")
    assert _organization_ids() == [7]


def test_auto_execute_respects_env(monkeypatch):
    monkeypatch.delenv("THIRAMAI_AUTONOMOUS_EXEC", raising=False)
    monkeypatch.delenv("THIRAMAI_ORCHESTRATOR_AUTO_MODE", raising=False)
    assert _auto_execute_flag() is False
    monkeypatch.setenv("THIRAMAI_AUTONOMOUS_EXEC", "1")
    assert _auto_execute_flag() is True
