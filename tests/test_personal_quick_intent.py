"""Quick-intent phrase parsing (voice / chat shortcuts)."""

from __future__ import annotations

from services.personal_quick_intent_sync import parse_quick_phrase


def test_strip_hey_thiramai_prefix() -> None:
    out = parse_quick_phrase("Hey Thiramai, add task call supplier")
    assert out.get("ok") is True
    assert out.get("action") == "add_task"
    assert out.get("title") == "call supplier"


def test_strip_hey_thiramai_no_comma() -> None:
    out = parse_quick_phrase("hey thiramai restock PVC pipe")
    assert out.get("ok") is True
    assert out.get("action") == "restock"
    assert (out.get("item") or "").lower() == "pvc pipe"


def test_research_feedback_colon() -> None:
    out = parse_quick_phrase("research feedback: assume Gujarat DISCOM delays 6 months")
    assert out.get("ok") is True
    assert out.get("action") == "research_feedback"
    assert "Gujarat" in (out.get("feedback") or "")


def test_research_correction_preserves_case() -> None:
    out = parse_quick_phrase("research correction Use MNRE 2024 benchmarks only")
    assert out.get("ok") is True
    assert (out.get("feedback") or "").startswith("Use MNRE")
