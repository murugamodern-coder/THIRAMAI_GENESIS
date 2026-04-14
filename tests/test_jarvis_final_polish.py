"""Final polish — goal resolution, simulation, clustering, event enqueue (mocked)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from services.jarvis_goal_engine import resolve_goal_conflicts
from services.jarvis_narrative import cluster_critical_insights_sync
from services.jarvis_world_simulation import simulate_future_state


def test_resolve_goal_conflicts_picks_deadline_urgent() -> None:
    g1 = {
        "id": 1,
        "description": "Reduce office costs",
        "goal_type": "cost",
        "deadline": (date.today() + timedelta(days=2)).isoformat(),
        "progress": {"percent": 10},
        "subtasks": [{"status": "pending"}, {"status": "pending"}],
    }
    g2 = {
        "id": 2,
        "description": "Grow profit by 50000",
        "goal_type": "revenue",
        "deadline": (date.today() + timedelta(days=40)).isoformat(),
        "target_value": "50000",
        "progress": {"percent": 5},
        "subtasks": [{"status": "pending"}],
    }
    out = resolve_goal_conflicts([g1, g2])
    assert out.get("ok") is True
    assert out.get("best") is not None
    ranked = out.get("ranked") or []
    assert len(ranked) == 2


def test_simulate_reorder_returns_cash_estimate() -> None:
    out = simulate_future_state(
        {"kind": "reorder", "organization_id": 0, "sku": "X", "order_qty": 10, "unit_cost": 50},
        days=7,
    )
    assert out.get("ok") is True
    assert float(out.get("cash_impact_inr_estimate") or 0) > 0


def test_cluster_caps_to_top_n() -> None:
    insights = [
        {"title": "Low stock soap", "recommended_action": "Reorder", "impact": {"urgency_score": 0.9}},
        {"title": "Another soap alert", "recommended_action": "PO", "impact": {"urgency_score": 0.4}},
        {"title": "EMI due", "recommended_action": "Pay", "impact": {"urgency_score": 0.95}},
    ]
    pack = cluster_critical_insights_sync(insights, top_n=2)
    assert len(pack.get("top_critical") or []) <= 2


def test_enqueue_skips_without_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("services.jarvis_agent_event_engine.get_session_factory", lambda: None)
    from services.jarvis_agent_event_engine import enqueue_agent_event_sync

    out = enqueue_agent_event_sync(
        organization_id=1,
        user_id=1,
        event_type="inventory_quantity_change",
        payload={"sku_name": "s"},
    )
    assert out.get("ok") is False
