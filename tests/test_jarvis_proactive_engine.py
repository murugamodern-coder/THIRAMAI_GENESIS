"""Living Jarvis Upgrade 2 — proactive engine helpers."""

from __future__ import annotations

from services.jarvis_proactive_engine import Insight, JarvisProactiveEngine, _dict_to_insight, _priority_rank


def test_priority_rank_urgent_first() -> None:
    assert _priority_rank("urgent") < _priority_rank("low")


def test_dict_to_insight_maps_tool() -> None:
    ins = _dict_to_insight(
        {
            "type": "reorder",
            "priority": "urgent",
            "message": "Soap is low stock",
            "action": "Reorder",
        }
    )
    assert ins is not None
    assert ins.action_tool == "create_purchase_order_draft"
    assert ins.priority_score == _priority_rank("urgent")


def test_insight_as_dict_roundtrip() -> None:
    i = Insight(
        priority="high",
        category="finance",
        title="Collect",
        message="Invoice overdue",
        action="Call",
        action_tool="draft_business_email",
        priority_score=1,
    )
    d = i.as_dict()
    assert d["category"] == "finance" and d["action_tool"] == "draft_business_email"


def test_engine_static_morning_delegates(monkeypatch) -> None:
    called: dict[str, bool] = {}

    def fake() -> dict:
        called["yes"] = True
        return {"ok": True, "users_processed": 0}

    monkeypatch.setattr(
        "services.jarvis_proactive_service.run_morning_job_all_users_sync",
        fake,
    )
    out = JarvisProactiveEngine.run_morning_intelligence_all_users()
    assert called.get("yes") is True
    assert out["ok"] is True
