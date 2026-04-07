"""Empire Governance Mode — exception-only UX and P&L governance helpers (no live Groq)."""

from __future__ import annotations

from core.brain_output import ActionIntentNone, BrainStructuredResponse, SellStockAction
from services import empire_governance


def test_exception_only_suppresses_chatter(monkeypatch):
    monkeypatch.setenv("THIRAMAI_EMPIRE_GOVERNANCE_MODE", "1")
    monkeypatch.setenv("THIRAMAI_EXCEPTION_ONLY_UX", "1")
    structured = BrainStructuredResponse(
        narrative="Here is a helpful summary of inventory levels for Tuesday.",
        action_intent=ActionIntentNone(),
    )
    out = empire_governance.maybe_apply_exception_only_ux(
        structured,
        route_tag="AgriCouncil",
        user_message="how is stock",
        structured_parse_ok=True,
    )
    assert out.empire_ux == "nominal_silence"
    assert out.narrative.strip() == ""


def test_exception_only_keeps_strategic_and_intent(monkeypatch):
    monkeypatch.setenv("THIRAMAI_EMPIRE_GOVERNANCE_MODE", "1")
    monkeypatch.setenv("THIRAMAI_EXCEPTION_ONLY_UX", "1")
    structured = BrainStructuredResponse(
        narrative="We need your approval to file revised GSTR-1 before the statutory deadline.",
        action_intent=ActionIntentNone(),
    )
    out = empire_governance.maybe_apply_exception_only_ux(
        structured,
        route_tag="AgriCouncil",
        user_message="?",
        structured_parse_ok=True,
    )
    assert out.empire_ux == "default"
    assert "GSTR" in out.narrative

    sell = BrainStructuredResponse(
        narrative="Posting sale.",
        action_intent=SellStockAction(sku_name="Soap", quantity=2.0),
    )
    out2 = empire_governance.maybe_apply_exception_only_ux(
        sell,
        route_tag="AgriCouncil",
        user_message="sell",
        structured_parse_ok=True,
    )
    assert out2.empire_ux == "default"


def test_exception_only_off_by_default():
    structured = BrainStructuredResponse(
        narrative="Short reply.",
        action_intent=ActionIntentNone(),
    )
    out = empire_governance.maybe_apply_exception_only_ux(
        structured,
        route_tag="AgriCouncil",
        user_message="x",
        structured_parse_ok=True,
    )
    assert out.narrative == "Short reply."
    assert out.empire_ux == "default"
