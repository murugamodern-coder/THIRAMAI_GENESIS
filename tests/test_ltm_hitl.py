"""HITL policy tightening and LTM mitigation formatting (no Chroma required)."""

from __future__ import annotations

from unittest.mock import patch

from services.action_policy import PolicyResult, evaluate_tool_action
from services.ltm_chroma import format_mitigation_block


def test_hitl_tightens_high_risk_allow_to_propose():
    with patch("services.hitl_rule_weights.strictness_multiplier", return_value=1.12):
        d = evaluate_tool_action(
            tool_id="inventory.sell_stock",
            organization_id=1,
            user_role_level=1,
            billing_paused=False,
        )
    assert d.result is PolicyResult.PROPOSE
    assert "HITL" in d.reason


def test_hitl_default_allows_high_risk_for_owner():
    with patch("services.hitl_rule_weights.strictness_multiplier", return_value=1.0):
        d = evaluate_tool_action(
            tool_id="inventory.sell_stock",
            organization_id=1,
            user_role_level=1,
            billing_paused=False,
        )
    assert d.result is PolicyResult.ALLOW


def test_mitigation_block_empty_without_ltm(monkeypatch):
    monkeypatch.delenv("THIRAMAI_LTM_ENABLED", raising=False)
    assert format_mitigation_block(organization_id=1, user_query="sell 5 units") == ""
