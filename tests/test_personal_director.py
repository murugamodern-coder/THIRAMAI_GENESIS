"""Personal AI Director bundle (no DB required for anonymous)."""

from __future__ import annotations

from unittest.mock import patch

from core.personal_director import build_personal_director_bundle_sync


def _snap() -> dict:
    return {
        "tasks": [{"id": 1, "title": "Ship report", "deadline": "2020-01-01T00:00:00+00:00", "status": "open"}],
        "reminders": [],
        "low_stock": {"ok": True, "items": [], "count": 0},
        "today_sales": {"ok": False},
        "authenticated": True,
        "user_id": 1,
        "organization_id": 0,
        "daily_score": 50,
        "streak_days": 2,
        "habits_completed_today": 0,
        "tasks_completed_today": 0,
    }


def test_director_anonymous_payload() -> None:
    payload = {"user_id": 0, "organization_id": 0, "authenticated": False}
    bundle = build_personal_director_bundle_sync(payload, _snap())
    assert bundle["life_context"]["mode"] == "reflect"
    assert bundle["priority_tasks"] == []
    assert bundle["proactive_alerts"] == []
    assert "health_score" in bundle["life_score"]


@patch(
    "core.personal_director.build_life_dashboard",
    return_value={
        "health_score": 70,
        "health_source": "mock",
        "productivity_score": 50,
        "financial_signal": "personal_only",
        "workload_level": "light",
        "as_of_utc": "",
    },
)
@patch("core.personal_director.detect_patterns_sync", return_value={"signals": [], "summary": "", "confidence": "low"})
@patch(
    "core.personal_director.get_user_profile_sync",
    return_value={
        "long_term_goals": [],
        "habits_history": {"active_habits": 0, "check_ins_last_14d": 0, "top_habits": []},
        "past_decisions": [],
        "recent_notes": [],
        "stats": {"open_missions": 0, "life_events_stored": 0},
    },
)
def test_director_priority_and_proactive(_mock_gp, _mock_dp, _mock_bld) -> None:
    payload = {
        "user_id": 1,
        "organization_id": 0,
        "authenticated": True,
        "tasks": _snap()["tasks"],
        "reminders": [],
        "low_stock": {"ok": True, "items": [], "count": 0},
        "today_sales": {"ok": False},
        "daily_score": 50,
    }
    bundle = build_personal_director_bundle_sync(payload, _snap(), engagement_extra={})
    assert bundle["priority_tasks"]
    assert bundle["priority_tasks"][0].get("title")
    assert any(a.get("code") == "missed_deadline" for a in bundle["proactive_alerts"])
    assert bundle["guidance_enrichment"].get("next_best_move")
    assert bundle["guidance_enrichment"].get("director_mode")
