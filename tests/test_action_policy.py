"""Policy kernel + tool registry (Phase 1)."""

from __future__ import annotations

from services.action_policy import PolicyResult, evaluate_tool_action
from core.actions.registry import ToolRisk, get_tool, register_tool, ToolSpec, ToolDomain


def test_registry_has_core_tools() -> None:
    assert get_tool("inventory.sell_stock") is not None
    assert get_tool("billing.issue_invoice") is not None
    assert get_tool("factory.stage2_machine_failure") is not None


def test_policy_blocks_unknown_tool() -> None:
    d = evaluate_tool_action(tool_id="nope", organization_id=1, user_role_level=1)
    assert d.result is PolicyResult.BLOCK


def test_policy_blocks_when_billing_paused_for_sell_stock() -> None:
    d = evaluate_tool_action(
        tool_id="inventory.sell_stock",
        organization_id=1,
        user_role_level=1,
        billing_paused=True,
    )
    assert d.result is PolicyResult.BLOCK


def test_policy_critical_invoice_propose() -> None:
    d = evaluate_tool_action(
        tool_id="billing.issue_invoice",
        organization_id=1,
        user_role_level=1,
        billing_paused=False,
    )
    assert d.result is PolicyResult.PROPOSE


def test_policy_customer_blocked() -> None:
    d = evaluate_tool_action(
        tool_id="inventory.read_stock",
        organization_id=1,
        user_role_level=5,
        billing_paused=False,
    )
    assert d.result is PolicyResult.BLOCK


def test_duplicate_register_raises() -> None:
    import uuid

    tid = f"test.dup.{uuid.uuid4().hex[:12]}"
    spec = ToolSpec(
        id=tid,
        domain=ToolDomain.INVENTORY,
        title="x",
        risk=ToolRisk.LOW,
    )
    register_tool(spec)
    try:
        register_tool(spec)
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "duplicate" in str(e).lower()
