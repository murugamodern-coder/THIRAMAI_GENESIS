"""Runnable PolicyEngine usage examples.

Run from the repository root:

    python examples/policy_engine_usage.py

The script never touches the database (organization_id is left ``None``) so it
works on a fresh checkout without any DB / migrations.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow ``python examples/policy_engine_usage.py`` to import top-level packages
# without installing the project; mirrors how tests run from the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from services.policy_engine import DecisionContext, get_policy_engine  # noqa: E402


def example_trading_decision() -> None:
    engine = get_policy_engine()

    context = DecisionContext(
        intent="analyze_trade_opportunity",
        domain="trading",
        user_id=1,
        risk_tolerance=0.6,
        time_horizon="short",
        constraints={"max_position_size": 10_000},
        metadata={"symbol": "RELIANCE", "current_price": 2500, "signal": "bullish"},
    )

    decision = engine.decide(context)

    print("=== TRADING DECISION ===")
    print(f"Action          : {decision.action}")
    print(f"Action Type     : {decision.action_type}")
    print(f"Confidence      : {decision.confidence:.2%}")
    print(f"Expected Reward : {decision.expected_reward:.3f}")
    print(f"Exploration     : {decision.exploration_bonus:.3f}")
    print("Reasoning:")
    for line in decision.reasoning:
        print(f"  - {line}")

    if decision.action == "buy":
        engine.update_from_outcome(
            decision_context=context,
            action=decision.action,
            outcome={"executed": True, "fill_price": 2505, "profit": 50},
            reward=0.7,
        )


def example_business_decision() -> None:
    engine = get_policy_engine()

    context = DecisionContext(
        intent="inventory_decision",
        domain="business",
        user_id=2,
        risk_tolerance=0.4,
        time_horizon="medium",
        constraints={"budget": 50_000},
        metadata={"product": "Widget A", "current_stock": 10, "demand_forecast": 50},
    )

    decision = engine.decide(context)

    print("\n=== BUSINESS DECISION ===")
    print(f"Action          : {decision.action}")
    print(f"Action Type     : {decision.action_type}")
    print(f"Confidence      : {decision.confidence:.2%}")
    print(f"Expected Reward : {decision.expected_reward:.3f}")

    engine.update_from_outcome(
        decision_context=context,
        action=decision.action,
        outcome={"sales": 45, "revenue": 67_500},
        reward=0.85,
    )


def example_personal_decision() -> None:
    engine = get_policy_engine()

    context = DecisionContext(
        intent="goal_prioritization",
        domain="personal",
        user_id=3,
        risk_tolerance=0.5,
        time_horizon="long",
        constraints={},
        metadata={
            "goal_a": "Learn Python",
            "goal_b": "Improve fitness",
            "available_hours": 10,
        },
    )

    decision = engine.decide(context)

    print("\n=== PERSONAL DECISION ===")
    print(f"Action          : {decision.action}")
    print(f"Confidence      : {decision.confidence:.2%}")

    engine.update_from_outcome(
        decision_context=context,
        action=decision.action,
        outcome={"satisfaction": "high", "progress": 0.8},
        reward=0.9,
    )


def example_learning_over_time() -> None:
    """Show the bandit converging when one action is consistently rewarded."""

    engine = get_policy_engine()
    print("\n=== LEARNING OVER TIME (10 iterations) ===")

    context = DecisionContext(
        intent="analyze_trade_opportunity",
        domain="trading",
        user_id=1,
        risk_tolerance=0.5,
        time_horizon="short",
        constraints={},
        metadata={"symbol": "TCS"},
    )

    for i in range(10):
        decision = engine.decide(context)
        reward = 0.8 if decision.action == "buy" else -0.3
        print(
            f"  iter={i + 1:2d} action={decision.action:<18} "
            f"confidence={decision.confidence:.2f} "
            f"exploration_bonus={decision.exploration_bonus:.2f} "
            f"reward={reward:+.2f}"
        )
        engine.update_from_outcome(
            decision_context=context,
            action=decision.action,
            outcome={"simulated": True},
            reward=reward,
        )

    counts = {a: rec["count"] for a, rec in engine.bandit.actions.items()}
    print(f"  bandit counts: {counts}")
    print("  Engine should converge towards 'buy' once enough reward is observed.")


if __name__ == "__main__":
    example_trading_decision()
    example_business_decision()
    example_personal_decision()
    example_learning_over_time()
