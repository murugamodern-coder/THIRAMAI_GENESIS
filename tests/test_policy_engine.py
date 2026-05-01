"""Tests for the centralised :class:`services.policy_engine.PolicyEngine`.

Run with: ``pytest tests/test_policy_engine.py -v``

The tests are DB-free: ``DecisionContext.organization_id`` is left ``None`` so
``_log_decision`` / ``_log_outcome`` short-circuit before touching the database.
"""

from __future__ import annotations

import numpy as np
import pytest

from services.policy_engine import (
    DecisionContext,
    DecisionOutput,
    LinUCBBandit,
    PolicyEngine,
    get_policy_engine,
    reset_policy_engine,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fresh_engine() -> PolicyEngine:
    """A clean engine per test (no shared bandit weights)."""

    return PolicyEngine(n_features=20, alpha=1.0)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_policy_engine()
    yield
    reset_policy_engine()


# ---------------------------------------------------------------------------
# LinUCBBandit
# ---------------------------------------------------------------------------


def test_linucb_initialization():
    bandit = LinUCBBandit(n_features=10, alpha=1.0)
    assert bandit.n_features == 10
    assert bandit.alpha == 1.0
    assert bandit.actions == {}


def test_linucb_select_action_initial_exploration_bonus():
    bandit = LinUCBBandit(n_features=5, alpha=1.0)
    context = np.array([1.0, 0.5, 0.3, 0.8, 0.2])
    actions = ["buy", "sell", "hold"]

    action, expected_reward, exploration_bonus = bandit.select_action(actions, context)

    assert action in actions
    assert isinstance(expected_reward, float)
    assert isinstance(exploration_bonus, float)
    # Fresh actions: A = I, so exploration_bonus = alpha * ||x|| > 0.
    assert exploration_bonus > 0.0


def test_linucb_update_writes_back_into_b_and_count():
    bandit = LinUCBBandit(n_features=5, alpha=1.0)
    context = np.array([1.0, 0.5, 0.3, 0.8, 0.2])
    actions = ["buy", "sell", "hold"]

    action, _, _ = bandit.select_action(actions, context)
    bandit.update(action, context, reward=0.8)

    assert action in bandit.actions
    assert bandit.actions[action]["count"] == 1
    assert not np.allclose(bandit.actions[action]["b"], np.zeros(5))


def test_linucb_prefers_high_reward_action_after_training():
    bandit = LinUCBBandit(n_features=3, alpha=0.1)  # low alpha → exploit faster
    context = np.array([1.0, 0.5, 0.8])
    actions = ["good", "bad"]

    for _ in range(20):
        bandit.update("good", context, reward=1.0)
        bandit.update("bad", context, reward=-1.0)

    selected, expected_reward, _ = bandit.select_action(actions, context)
    assert selected == "good"
    assert expected_reward > 0


def test_linucb_rejects_wrong_feature_dim():
    bandit = LinUCBBandit(n_features=4, alpha=1.0)
    with pytest.raises(ValueError):
        bandit.select_action(["x"], np.array([1.0, 2.0]))


def test_linucb_rejects_empty_action_list():
    bandit = LinUCBBandit(n_features=3, alpha=1.0)
    with pytest.raises(ValueError):
        bandit.select_action([], np.array([1.0, 2.0, 3.0]))


# ---------------------------------------------------------------------------
# PolicyEngine
# ---------------------------------------------------------------------------


def test_policy_engine_initialization(fresh_engine: PolicyEngine):
    assert fresh_engine.n_features == 20
    assert fresh_engine.bandit is not None
    assert len(fresh_engine.action_registry) > 0


def test_policy_engine_decide_trading(fresh_engine: PolicyEngine):
    context = DecisionContext(
        intent="analyze_trade_opportunity",
        domain="trading",
        user_id=1,
        risk_tolerance=0.5,
        time_horizon="short",
        constraints={},
        metadata={},
    )

    output = fresh_engine.decide(context)

    assert isinstance(output, DecisionOutput)
    assert output.action in {"buy", "sell", "hold", "add_to_watchlist"}
    assert 0.0 <= output.confidence <= 1.0
    assert output.action_type == "trading"
    assert isinstance(output.reasoning, list) and len(output.reasoning) >= 4
    assert len(output.features) == fresh_engine.n_features
    assert output.timestamp is not None


def test_policy_engine_update_from_outcome_uses_cached_features(
    fresh_engine: PolicyEngine,
):
    context = DecisionContext(
        intent="analyze_trade_opportunity",
        domain="trading",
        user_id=1,
        risk_tolerance=0.5,
        time_horizon="short",
        constraints={},
        metadata={},
    )
    output = fresh_engine.decide(context)

    fresh_engine.update_from_outcome(
        decision_context=context,
        action=output.action,
        outcome={"success": True, "profit": 100},
        reward=0.8,
    )

    assert output.action in fresh_engine.bandit.actions
    assert fresh_engine.bandit.actions[output.action]["count"] >= 1


def test_policy_engine_feature_extraction_shape_and_finiteness(
    fresh_engine: PolicyEngine,
):
    context = DecisionContext(
        intent="pricing_decision",
        domain="business",
        user_id=5,
        risk_tolerance=0.7,
        time_horizon="medium",
        constraints={"max_discount": 0.2},
        metadata={"product": "widget"},
    )
    features = fresh_engine._extract_features(context, {"features": {}})

    assert features.shape == (fresh_engine.n_features,)
    assert np.isfinite(features).all()


def test_policy_engine_action_registry_contents(fresh_engine: PolicyEngine):
    assert "analyze_trade_opportunity" in fresh_engine.action_registry
    assert "buy" in fresh_engine.action_registry["analyze_trade_opportunity"]
    assert "inventory_decision" in fresh_engine.action_registry
    assert "purchase_inventory" in fresh_engine.action_registry["inventory_decision"]
    assert "trading_default" in fresh_engine.action_registry
    assert "hold" in fresh_engine.action_registry["trading_default"]


def test_get_policy_engine_singleton():
    engine1 = get_policy_engine()
    engine2 = get_policy_engine()
    assert engine1 is engine2


def test_policy_engine_confidence_monotonicity(fresh_engine: PolicyEngine):
    high = fresh_engine._compute_confidence(expected_reward=0.9, exploration_bonus=0.1)
    low = fresh_engine._compute_confidence(expected_reward=-0.5, exploration_bonus=1.5)
    assert high > low
    assert 0.0 <= high <= 1.0
    assert 0.0 <= low <= 1.0


def test_policy_engine_reasoning_generation(fresh_engine: PolicyEngine):
    context = DecisionContext(
        intent="manage_position",
        domain="trading",
        user_id=1,
        risk_tolerance=0.3,
        time_horizon="immediate",
        constraints={},
        metadata={},
    )

    reasoning = fresh_engine._generate_reasoning(
        action="close_position",
        context=context,
        world_state={"prediction": {}},
        expected_reward=0.6,
        exploration_bonus=0.2,
    )

    assert isinstance(reasoning, list)
    assert len(reasoning) >= 5
    assert any("close_position" in line for line in reasoning)
    assert any("Risk tolerance" in line for line in reasoning)


def test_policy_engine_unknown_intent_falls_back_to_domain_default(
    fresh_engine: PolicyEngine,
):
    context = DecisionContext(
        intent="completely_unknown_intent",
        domain="trading",
        user_id=1,
        risk_tolerance=0.5,
        time_horizon="short",
        constraints={},
        metadata={},
    )
    actions = fresh_engine._get_available_actions(context)
    assert actions
    assert "hold" in actions  # trading_default includes hold


def test_policy_engine_multi_domain_smoke(fresh_engine: PolicyEngine):
    intents = {
        "trading": "analyze_trade_opportunity",
        "business": "inventory_decision",
        "personal": "goal_prioritization",
        "system": "resource_allocation",
    }
    for domain, intent in intents.items():
        context = DecisionContext(
            intent=intent,
            domain=domain,
            user_id=1,
            risk_tolerance=0.5,
            time_horizon="short",
            constraints={},
            metadata={},
        )
        output = fresh_engine.decide(context)
        assert output.action
        assert output.action_type in {"trading", "business", "personal", "system"}


def test_policy_engine_features_are_stable_across_processes_proxy():
    """Hashing must be deterministic; rebuild the engine and re-extract."""

    e1 = PolicyEngine(n_features=20, alpha=1.0)
    e2 = PolicyEngine(n_features=20, alpha=1.0)
    ctx = DecisionContext(
        intent="pricing_decision",
        domain="business",
        user_id=42,
        risk_tolerance=0.4,
        time_horizon="medium",
        constraints={},
        metadata={},
    )
    f1 = e1._extract_features(ctx, {"features": {}})
    f2 = e2._extract_features(ctx, {"features": {}})
    # Time-of-day features differ when the second extraction crosses an hour
    # boundary; comparing the stable categorical / hash columns is sufficient.
    assert f1[1] == f2[1]  # domain bucket
    assert f1[3] == f2[3]  # time_horizon bucket
    assert f1[9] == f2[9]  # intent hash


def test_policy_engine_rejects_non_context_input(fresh_engine: PolicyEngine):
    with pytest.raises(TypeError):
        fresh_engine.decide("not a context")  # type: ignore[arg-type]


def test_policy_engine_decide_no_actions_raises(fresh_engine: PolicyEngine):
    fresh_engine.action_registry = {}
    context = DecisionContext(
        intent="x_unknown",
        domain="zzz",
        user_id=None,
        risk_tolerance=0.5,
        time_horizon="short",
    )
    with pytest.raises(ValueError):
        fresh_engine.decide(context)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
