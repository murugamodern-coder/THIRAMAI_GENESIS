"""Upgrade 2.2 — autonomous agent safety, learning hooks, continuous runner."""

from __future__ import annotations

import pytest

from services.jarvis_autonomous_agent import (
    is_safe_autonomous_action,
    maybe_upgrade_execution_mode_fact_sync,
    proactive_noise_cooldown_scale_sync,
    run_agent_cycle_sync,
    run_continuous_agent,
    update_learning_stats_sync,
)
from services.jarvis_goal_engine import _default_subtask_titles, create_goal_sync


def test_forbidden_auto_blocks_payments() -> None:
    assert is_safe_autonomous_action("payment_execute") is False
    assert is_safe_autonomous_action("stock_trade") is False
    assert is_safe_autonomous_action("create_purchase_order_draft") is True
    assert is_safe_autonomous_action("goal_subtask") is True


def test_default_subtasks_for_profit_goal() -> None:
    titles = _default_subtask_titles("Increase business profit by ₹50,000 this month", "revenue")
    assert len(titles) >= 3
    assert any("revenue" in t.lower() or "invoice" in t.lower() or "pricing" in t.lower() for t in titles)


def test_create_goal_requires_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("services.jarvis_goal_engine.get_session_factory", lambda: None)
    out = create_goal_sync(user_id=1, description="Test goal")
    assert out.get("ok") is False


def test_run_cycle_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    import time as _time

    monkeypatch.setattr("services.jarvis_autonomous_agent.generate_plan_sync", lambda **kw: [])
    monkeypatch.setattr("services.jarvis_autonomous_agent._cycle_interval_seconds", lambda: 3600.0)
    import services.jarvis_autonomous_agent as m

    m._LAST_CYCLE_TS[99] = _time.monotonic()
    r1 = run_agent_cycle_sync(user_id=99, organization_ids=[1])
    assert r1.get("skipped") == "rate_limited"


def test_continuous_agent_single_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_cycle(**kwargs: object) -> dict:
        calls.append(1)
        return {"ok": True, "stub": True}

    monkeypatch.setattr("services.jarvis_autonomous_agent.run_agent_cycle_sync", fake_cycle)
    out = run_continuous_agent(5, organization_ids=[1], forever=False, max_cycles=1)
    assert len(out) == 1 and calls == [1]


def test_maybe_upgrade_when_high_acceptance(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_count(**kwargs: object) -> int:
        o = str(kwargs.get("outcome", ""))
        if o == "acted":
            return 10
        if o == "ignored":
            return 2
        return 0

    monkeypatch.setattr("services.jarvis_proactive_intelligence.count_recent_outcomes_sync", fake_count)
    monkeypatch.setattr("services.jarvis_autonomous_agent.get_session_factory", lambda: None)
    out = maybe_upgrade_execution_mode_fact_sync(user_id=1)
    assert out.get("upgraded") is False


def test_noise_scale_high_ignore(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "services.jarvis_proactive_intelligence.count_recent_outcomes_sync",
        lambda **kw: 12 if kw.get("outcome") == "ignored" else 0,
    )
    assert proactive_noise_cooldown_scale_sync(user_id=1, alert_type="reorder") < 0.5


def test_update_learning_stats_no_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("services.jarvis_autonomous_agent.get_session_factory", lambda: None)
    update_learning_stats_sync(user_id=1, action_kind="noop", outcome="success")
