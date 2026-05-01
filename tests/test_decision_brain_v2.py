"""Tests for :mod:`services.decision_brain_v2`.

These tests avoid ``pytest-asyncio`` (not always installed in the dev env) by
running coroutines via :func:`asyncio.run`. They also avoid touching the
database — ``DecisionContext.organization_id`` is left ``None`` so persistence
short-circuits cleanly.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from services.decision_brain_v2 import (
    DecisionBrainV2,
    get_decision_brain_v2,
    reset_decision_brain_v2,
)
from services.policy_engine import (
    DecisionOutput,
    PolicyEngine,
    reset_policy_engine,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_policy_engine()
    reset_decision_brain_v2()
    yield
    reset_policy_engine()
    reset_decision_brain_v2()


@pytest.fixture()
def fresh_brain() -> DecisionBrainV2:
    return DecisionBrainV2(policy_engine=PolicyEngine(n_features=20, alpha=1.0))


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def test_initialization(fresh_brain: DecisionBrainV2):
    assert fresh_brain.policy_engine is not None
    assert 0.0 <= fresh_brain.policy_engine_percentage <= 100.0


def test_routing_is_deterministic_per_user(fresh_brain: DecisionBrainV2):
    fresh_brain.ab_test_enabled = True
    fresh_brain.policy_engine_percentage = 50.0
    same = {fresh_brain._should_use_policy_engine(7) for _ in range(20)}
    assert len(same) == 1


def test_routing_off_uses_policy_engine(fresh_brain: DecisionBrainV2):
    fresh_brain.ab_test_enabled = False
    assert fresh_brain._should_use_policy_engine(None) is True
    assert fresh_brain._should_use_policy_engine(99) is True


def test_routing_buckets_by_user_id(fresh_brain: DecisionBrainV2):
    fresh_brain.ab_test_enabled = True
    fresh_brain.policy_engine_percentage = 50.0
    # user_id = 10 → bucket 10 < 50 → policy
    # user_id = 90 → bucket 90 >= 50 → legacy
    assert fresh_brain._should_use_policy_engine(10) is True
    assert fresh_brain._should_use_policy_engine(90) is False


# ---------------------------------------------------------------------------
# Policy-engine variant
# ---------------------------------------------------------------------------


def test_decide_with_policy_engine(fresh_brain: DecisionBrainV2):
    decision = asyncio.run(
        fresh_brain._decide_with_policy_engine(
            intent="analyze_trade_opportunity",
            context={"symbol": "RELIANCE"},
            user_id=1,
            domain="trading",
            organization_id=None,
        )
    )

    assert decision["source"] == "policy_engine"
    assert "action" in decision
    assert decision["action_type"] == "trading"
    assert 0.0 <= decision["confidence"] <= 1.0
    # Round-trip context for record_outcome:
    assert decision["intent"] == "analyze_trade_opportunity"
    assert decision["domain"] == "trading"


def test_full_decide_routes_through_policy(fresh_brain: DecisionBrainV2):
    fresh_brain.ab_test_enabled = False
    decision = asyncio.run(
        fresh_brain.decide(
            intent="analyze_trade_opportunity",
            context={"symbol": "TCS"},
            user_id=1,
            domain="trading",
        )
    )
    assert decision["source"] == "policy_engine"


# ---------------------------------------------------------------------------
# Legacy variant + fallback
# ---------------------------------------------------------------------------


def test_legacy_variant_returns_unified_payload(
    fresh_brain: DecisionBrainV2, monkeypatch: pytest.MonkeyPatch
):
    """Legacy brain unavailable (no GROQ_API_KEY) → unified ``noop`` payload."""

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    decision = asyncio.run(
        fresh_brain._decide_with_legacy(
            intent="reorder_stock",
            context={"user_message": "stock low"},
            user_id=1,
            domain="business",
            organization_id=None,
        )
    )
    assert decision["source"] == "legacy_brain"
    assert decision["action"] == "noop"
    assert decision["confidence"] == 0.0
    assert decision["reasoning"]
    assert decision["intent"] == "reorder_stock"


def test_fallback_to_legacy_when_policy_engine_raises(
    fresh_brain: DecisionBrainV2, monkeypatch: pytest.MonkeyPatch
):
    def boom(*_a: Any, **_kw: Any) -> DecisionOutput:
        raise RuntimeError("simulated bandit failure")

    monkeypatch.setattr(fresh_brain.policy_engine, "decide", boom)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    decision = asyncio.run(
        fresh_brain._decide_with_policy_engine(
            intent="analyze_trade_opportunity",
            context={},
            user_id=1,
            domain="trading",
            organization_id=None,
        )
    )
    assert decision["source"] == "legacy_brain"


# ---------------------------------------------------------------------------
# Outcome routing
# ---------------------------------------------------------------------------


def test_record_outcome_only_updates_policy_engine_for_policy_decisions(
    fresh_brain: DecisionBrainV2,
):
    decision = asyncio.run(
        fresh_brain._decide_with_policy_engine(
            intent="analyze_trade_opportunity",
            context={"symbol": "INFY"},
            user_id=1,
            domain="trading",
            organization_id=None,
        )
    )
    pre = dict(fresh_brain.policy_engine.bandit.actions[decision["action"]])
    asyncio.run(
        fresh_brain.record_outcome(
            decision=decision,
            outcome={"profit": 100},
            reward=0.7,
        )
    )
    post = fresh_brain.policy_engine.bandit.actions[decision["action"]]
    assert post["count"] == int(pre["count"]) + 1


def test_record_outcome_legacy_does_not_touch_bandit(
    fresh_brain: DecisionBrainV2, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    decision = asyncio.run(
        fresh_brain._decide_with_legacy(
            intent="reorder_stock",
            context={"user_message": "stock low"},
            user_id=1,
            domain="business",
            organization_id=None,
        )
    )
    bandit = fresh_brain.policy_engine.bandit
    pre_actions = {a: rec["count"] for a, rec in bandit.actions.items()}
    asyncio.run(
        fresh_brain.record_outcome(
            decision=decision,
            outcome={"any": "thing"},
            reward=0.5,
        )
    )
    post_actions = {a: rec["count"] for a, rec in bandit.actions.items()}
    assert pre_actions == post_actions


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


def test_get_decision_brain_v2_singleton():
    a = get_decision_brain_v2()
    b = get_decision_brain_v2()
    assert a is b


def test_env_overrides(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("THIRAMAI_DECISION_AB_TEST", "false")
    monkeypatch.setenv("THIRAMAI_POLICY_ENGINE_PCT", "75")
    reset_decision_brain_v2()
    brain = DecisionBrainV2()
    assert brain.ab_test_enabled is False
    assert brain.policy_engine_percentage == 75.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
