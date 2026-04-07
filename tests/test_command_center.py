"""Command center aggregation and priority classifier."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from core.routine_brief import try_routine_brief_only
from services.command_center import classify_action_priorities, user_requests_command_center


def test_user_requests_command_center():
    assert user_requests_command_center("Show me the command center") is True
    assert user_requests_command_center("unified dashboard please") is True
    assert user_requests_command_center("what is the weather") is False


@patch("services.command_center.build_business_snapshot", return_value={"ok": False})
@patch("services.command_center.list_pending_hitl")
@patch("services.command_center.get_inventory_alerts")
@patch("services.command_center.executive_core.load_user_profile")
def test_classify_gstr1_followup_window(mock_prof, mock_inv, mock_hitl, _mock_biz):
    mock_hitl.return_value = []
    mock_inv.return_value = {"ok": True, "items": []}
    mock_prof.return_value = {"key_meetings": []}
    anchor = datetime(2026, 3, 13, 12, 0, tzinfo=timezone.utc)
    out = classify_action_priorities(organization_id=1, _as_of=anchor)
    assert any(
        x.get("tier") == "emergency" and "GSTR-1" in (x.get("title") or "") for x in out
    )


@patch("services.command_center.build_business_snapshot", return_value={"ok": False})
@patch("services.command_center.list_pending_hitl")
@patch("services.command_center.get_inventory_alerts")
@patch("services.command_center.executive_core.load_user_profile")
def test_classify_missed_meeting_date(mock_prof, mock_inv, mock_hitl, _mock_biz):
    mock_hitl.return_value = []
    mock_inv.return_value = {"ok": True, "items": []}
    mock_prof.return_value = {"key_meetings": ["Board review on 2020-01-01"]}
    anchor = datetime(2026, 6, 1, tzinfo=timezone.utc)
    out = classify_action_priorities(organization_id=1, _as_of=anchor)
    meeting_em = [x for x in out if x.get("source") == "meeting" and x.get("tier") == "emergency"]
    assert meeting_em
    assert "past" in (meeting_em[0].get("title") or "").lower()


@patch("core.routine_brief.build_unified_snapshot")
def test_routine_brief_command_center_short_narrative(mock_snap, monkeypatch):
    monkeypatch.setenv("THIRAMAI_ROUTINE_BRIEF", "1")
    mock_snap.return_value = {
        "ok": True,
        "priority_counts": {"emergency": 0, "urgent": 1, "later": 2},
        "pending_hitl": [{"id": "x"}],
        "priority_queue": [{"emoji": "🟠", "title": "Test urgent item"}],
        "inventory_alerts": {"count": 3},
    }
    out = try_routine_brief_only("open command center", 1, actor_role_name="admin")
    assert out is not None
    assert "Action Completed" in out.narrative
    assert "Command center" in out.narrative
