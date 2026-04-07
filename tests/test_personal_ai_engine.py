"""Unit tests for deterministic personal daily guidance."""

from __future__ import annotations

from core.personal_ai_engine import generate_daily_guidance, generate_evening_summary


def test_guidance_signed_out() -> None:
    g = generate_daily_guidance({"authenticated": False, "user_id": 0, "organization_id": 0})
    assert g.get("top_focus")
    assert g.get("focus") == g.get("top_focus")
    assert "alerts" in g and "suggestions" in g
    assert g["actionable_suggestions"]
    assert g["alerts"] and any("sign" in a.lower() for a in g["alerts"])
    assert g.get("message")
    assert g.get("tone") == "warm"
    assert "focus_lock" in g and g.get("focus_lock") == ""


def test_guidance_no_sales_and_low_stock() -> None:
    ctx = {
        "authenticated": True,
        "user_id": 1,
        "organization_id": 1,
        "tasks": [{"id": 1, "title": "Call vendor"}],
        "reminders": [],
        "low_stock": {
            "ok": True,
            "count": 1,
            "items": [{"sku_name": "PVC pipe", "quantity": 2}],
        },
        "today_sales": {
            "ok": True,
            "revenue_inr": {"today": "0"},
        },
    }
    g = generate_daily_guidance(ctx, memory=None, followups=None)
    assert len(g.get("actionable_suggestions") or []) <= 3
    assert g.get("message")
    assert g.get("tone")
    assert g.get("time_mode")
    assert g.get("focus_lock")
    assert g.get("top_focus")
    assert isinstance(g.get("secondary"), list)
    assert isinstance(g.get("low_priority"), list)
    assert any("No sales" in a or "sales" in a.lower() for a in g["alerts"]) or any(
        "sales" in s.lower() for s in g["suggestions"]
    )
    assert any("PVC" in s or "Restock" in s for s in g["suggestions"])
    act = g.get("actionable_suggestions") or []
    assert any("restock" == x.get("action") for x in act)
    assert any(x.get("action_type") == "api_call" and x.get("endpoint") == "/personal/action" for x in act)
    ev = generate_evening_summary(ctx)
    assert ev.get("summary")
    assert "tomorrow_hint" in ev


def test_actionable_complete_task_shape() -> None:
    ctx = {
        "authenticated": True,
        "user_id": 2,
        "organization_id": 1,
        "tasks": [{"id": 42, "title": "Ship order"}],
        "reminders": [],
        "low_stock": {"ok": True, "count": 0, "items": []},
        "today_sales": {"ok": True, "revenue_inr": {"today": "100"}},
    }
    g = generate_daily_guidance(ctx)
    act = g.get("actionable_suggestions") or []
    ct = [x for x in act if x.get("action") == "complete_task"]
    assert ct
    assert ct[0].get("body", {}).get("mission_id") == 42


def test_memory_ranking_boosts_restock_when_complete_task_suppressed() -> None:
    ctx = {
        "authenticated": True,
        "user_id": 1,
        "organization_id": 1,
        "tasks": [{"id": 1, "title": "Call vendor"}],
        "reminders": [],
        "low_stock": {
            "ok": True,
            "count": 1,
            "items": [{"sku_name": "PVC pipe", "quantity": 2}],
        },
        "today_sales": {"ok": True, "revenue_inr": {"today": "0"}},
    }
    memory = {
        "boost_actions": {"restock": 10},
        "suppress_actions": {"complete_task": 10},
        "boost_phrases": [],
        "suppress_phrases": [],
    }
    g = generate_daily_guidance(ctx, memory=memory)
    act = g.get("actionable_suggestions") or []
    assert act, "expected actionable rows"
    assert act[0].get("action") == "restock"


def test_followups_prepended_to_alerts() -> None:
    ctx = {
        "authenticated": True,
        "user_id": 1,
        "organization_id": 1,
        "tasks": [],
        "reminders": [],
        "low_stock": {"ok": True, "count": 0, "items": []},
        "today_sales": {"ok": True, "revenue_inr": {"today": "100"}},
    }
    g = generate_daily_guidance(ctx, followups=["Yesterday you didn't restock PVC pipe"])
    assert g.get("followups") == ["Yesterday you didn't restock PVC pipe"]
    assert g["alerts"] and "PVC" in g["alerts"][0]


def test_time_mode_morning_override() -> None:
    ctx = {
        "authenticated": True,
        "user_id": 1,
        "organization_id": 1,
        "jarvis_hour_utc": 8,
        "tasks": [],
        "reminders": [],
        "low_stock": {"ok": True, "count": 0, "items": []},
        "today_sales": {"ok": True, "revenue_inr": {"today": "100"}},
    }
    g = generate_daily_guidance(ctx)
    assert g.get("time_mode") == "morning"
    assert g.get("top_focus", "").startswith("Morning • ")
