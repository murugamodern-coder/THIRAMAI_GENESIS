"""Upgrade 2.1 — agentic scoring, EMI escalation, learning loop, PO draft payload."""

from __future__ import annotations

import pytest

from services.jarvis_proactive_engine import _dict_to_insight, Insight
from services.jarvis_proactive_action_engine import try_execute_create_po_draft, user_execution_mode


def test_to_agentic_output_shape() -> None:
    i = Insight(
        priority="high",
        category="collection",
        title="Overdue",
        message="Pay up",
        action="Call",
        reasoning="Because cash cycle",
        recommended_action="Send reminder",
        impact_score=0.7,
        urgency_score=0.8,
        confidence_score=0.65,
        weighted_priority_score=72.5,
        action_ready_payload={"ok": True, "handler": "draft"},
    )
    out = i.to_agentic_output()
    assert set(out.keys()) >= {"title", "reasoning", "impact", "recommended_action", "action_ready_payload"}
    assert out["impact"]["priority_score"] == 72.5


def test_low_stock_maps_po_draft_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_po(**kwargs: object) -> dict:
        return {
            "ok": True,
            "handler": "create_purchase_order_draft",
            "organization_id": 1,
            "supplier_id": 99,
            "lines": [{"sku_name": "soap", "quantity_ordered": "3", "unit_cost_pre_tax": "10"}],
        }

    monkeypatch.setattr(
        "services.jarvis_proactive_action_engine.build_reorder_po_draft_payload_sync",
        _fake_po,
    )
    ins = _dict_to_insight(
        {
            "_user_id": 42,
            "type": "reorder",
            "priority": "urgent",
            "message": "Soap is low stock",
            "action": "Reorder",
            "organization_id": 1,
            "dedupe_key": "lowstock:1:soap",
            "payload": {"sku": "soap", "quantity": 2},
        }
    )
    assert ins is not None
    assert ins.action_tool == "create_purchase_order_draft"
    assert ins.action_ready_payload.get("handler") == "create_purchase_order_draft"
    assert ins.action_ready_payload.get("supplier_id") == 99


def test_emi_escalation_when_low_cash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "services.jarvis_proactive_intelligence.fetch_memory_snippets_sync",
        lambda **kwargs: {"facts": [], "cash_stress": True, "prefers_upi": True},
    )
    ins = _dict_to_insight(
        {
            "_user_id": 7,
            "type": "payment",
            "priority": "urgent",
            "message": "EMI ₹5000 due in 2 day(s) — Car loan.",
            "action": "Transfer funds",
            "dedupe_key": "emi:7:2026-04-10:car",
            "payload": {"loan_id": 1},
            "organization_id": None,
        }
    )
    assert ins is not None
    assert "Escalation" in ins.message
    assert ins.urgency_score >= 0.88


def test_equity_risk_downweighted_after_ignores(monkeypatch: pytest.MonkeyPatch) -> None:
    def _count(**kwargs: object) -> int:
        if str(kwargs.get("outcome")) == "ignored" and str(kwargs.get("alert_type")) == "equity_risk":
            return 8
        return 0

    monkeypatch.setattr("services.jarvis_proactive_intelligence.count_recent_outcomes_sync", _count)
    ins = _dict_to_insight(
        {
            "_user_id": 3,
            "type": "equity_risk",
            "priority": "high",
            "message": "Equity loss cap hit",
            "action": "Review",
            "organization_id": 1,
            "dedupe_key": "equity_risk:3:2026-04-07",
            "payload": {"daily_realized_pnl_inr": "-5000"},
        }
    )
    assert ins is not None
    assert ins.impact_score < 0.86


def test_auto_po_draft_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THIRAMAI_PROACTIVE_EXECUTION_MODE", "auto")
    monkeypatch.setenv("THIRAMAI_PROACTIVE_AUTO_PO_DRAFT", "1")

    def _fake(**kwargs: object) -> dict:
        return {"executed": True, "result": {"ok": True, "purchase_order": {"id": 555}}}

    monkeypatch.setattr("services.inventory_phase2_service.create_purchase_order_sync", _fake)
    payload = {
        "ok": True,
        "handler": "create_purchase_order_draft",
        "organization_id": 1,
        "supplier_id": 2,
        "order_date": "2026-04-07",
        "lines": [{"sku_name": "x", "quantity_ordered": "1", "unit_cost_pre_tax": "1"}],
    }
    out = try_execute_create_po_draft(user_id=9, payload=payload)
    assert out is not None
    assert out.get("executed") is True
    assert user_execution_mode() == "auto"

    monkeypatch.delenv("THIRAMAI_PROACTIVE_EXECUTION_MODE", raising=False)
    monkeypatch.delenv("THIRAMAI_PROACTIVE_AUTO_PO_DRAFT", raising=False)
