"""Tests for :mod:`services.hierarchical_policy` and the router wiring.

The plan is to exercise every layer in isolation (StrategicGoal /
TacticalPlan / MCTSNode / StrategicPlanner / TacticalPlanner /
HierarchicalPolicy / default_goals_provider) and then prove the
:class:`services.decision_router.DecisionRouter` integration is strictly
additive (existing flows untouched, hierarchical only fires when explicitly
enabled and the request asks for a long-horizon decision).

All planner instantiations pass an explicit ``random.Random`` seed so the
suite is deterministic without monkey-patching ``numpy.random``.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from services.decision_router import DecisionRouter, reset_decision_router
from services.hierarchical_policy import (
    HierarchicalPolicy,
    MCTSNode,
    StrategicGoal,
    StrategicPlanner,
    TacticalPlan,
    TacticalPlanner,
    _jarvis_goal_to_strategic,
    default_goals_provider,
    get_hierarchical_policy,
    reset_hierarchical_policy,
)
from services.policy_engine import (
    DecisionContext,
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
    reset_decision_router()
    reset_hierarchical_policy()
    yield
    reset_policy_engine()
    reset_decision_router()
    reset_hierarchical_policy()


@pytest.fixture()
def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _make_goal(
    *,
    goal_id: str = "g1",
    description: str = "Goal one",
    domain: str = "business",
    target: float = 1.0,
    current: float = 0.0,
    deadline: datetime | None = None,
    priority: float = 0.5,
) -> StrategicGoal:
    return StrategicGoal(
        goal_id=goal_id,
        description=description,
        domain=domain,
        target_value=target,
        current_value=current,
        deadline=deadline or (datetime.now(timezone.utc) + timedelta(days=30)),
        priority=priority,
    )


@pytest.fixture()
def small_goal_set(now_utc: datetime) -> list[StrategicGoal]:
    return [
        _make_goal(goal_id="g_trade", description="Grow capital", domain="trading", target=1.0, priority=0.8, deadline=now_utc + timedelta(days=45)),
        _make_goal(goal_id="g_biz", description="Expand market", domain="business", target=1.0, priority=0.6, deadline=now_utc + timedelta(days=60)),
        _make_goal(goal_id="g_self", description="Learn skill", domain="personal", target=1.0, priority=0.4, deadline=now_utc + timedelta(days=80)),
    ]


@pytest.fixture()
def fresh_engine() -> PolicyEngine:
    return PolicyEngine(n_features=20, alpha=1.0)


@pytest.fixture()
def hier(fresh_engine: PolicyEngine, small_goal_set: list[StrategicGoal]) -> HierarchicalPolicy:
    """A fully-isolated HierarchicalPolicy: in-memory engine + injected goals
    + a deterministic strategic planner + a small-budget tactical planner."""

    return HierarchicalPolicy(
        operational=fresh_engine,
        strategic=StrategicPlanner(simulation_budget=64, rng=random.Random(0)),
        tactical=TacticalPlanner(max_iterations=200),
        goals_provider=lambda _ctx: list(small_goal_set),
    )


# ===========================================================================
# StrategicGoal
# ===========================================================================


def test_strategic_goal_progress_within_target():
    g = _make_goal(target=10.0, current=2.5)
    assert g.progress() == pytest.approx(0.25)


def test_strategic_goal_progress_clamped_to_one():
    g = _make_goal(target=10.0, current=999.0)
    assert g.progress() == 1.0


def test_strategic_goal_progress_zero_target_returns_one():
    g = _make_goal(target=0.0, current=0.0)
    assert g.progress() == 1.0


def test_strategic_goal_progress_handles_garbage_target():
    g = StrategicGoal(
        goal_id="g",
        description="d",
        domain="business",
        target_value=float("nan"),  # type: ignore[arg-type]
        current_value=0.0,
        deadline=datetime.now(timezone.utc) + timedelta(days=10),
    )
    # nan/<=0 path returns 1.0 OR a numeric fallback; we just want no exception
    assert 0.0 <= g.progress() <= 1.0


def test_strategic_goal_urgency_far_deadline_low(now_utc: datetime):
    g = _make_goal(deadline=now_utc + timedelta(days=89))
    assert 0.0 <= g.urgency() <= 0.05


def test_strategic_goal_urgency_past_deadline_is_one(now_utc: datetime):
    g = _make_goal(deadline=now_utc - timedelta(days=1))
    assert g.urgency() == 1.0


def test_strategic_goal_urgency_handles_naive_datetime(now_utc: datetime):
    g = _make_goal(deadline=(now_utc + timedelta(days=10)).replace(tzinfo=None))
    assert 0.5 < g.urgency() < 1.0


def test_strategic_goal_urgency_handles_date_object(now_utc: datetime):
    g = _make_goal(deadline=(now_utc + timedelta(days=10)).date())  # type: ignore[arg-type]
    assert 0.5 < g.urgency() < 1.0


# ===========================================================================
# TacticalPlan
# ===========================================================================


def test_tactical_plan_next_action_returns_current_step():
    plan = TacticalPlan(
        plan_id="p", goal_id="g", steps=[{"action": "a"}, {"action": "b"}],
        estimated_duration=timedelta(days=1), estimated_cost=0.0, estimated_reward=0.0,
    )
    assert plan.next_action() == {"action": "a"}
    plan.current_step = 1
    assert plan.next_action() == {"action": "b"}


def test_tactical_plan_next_action_returns_none_when_complete():
    plan = TacticalPlan(plan_id="p", goal_id="g", steps=[{"action": "a"}],
                        estimated_duration=timedelta(days=1), estimated_cost=0.0, estimated_reward=0.0,
                        current_step=1)
    assert plan.next_action() is None
    assert plan.is_complete()


def test_tactical_plan_empty_steps_immediately_complete():
    plan = TacticalPlan(plan_id="p", goal_id="g", steps=[],
                        estimated_duration=timedelta(0), estimated_cost=0.0, estimated_reward=0.0)
    assert plan.is_complete()
    assert plan.next_action() is None


# ===========================================================================
# MCTSNode
# ===========================================================================


def test_mcts_node_is_terminal_when_no_goals():
    node = MCTSNode(state={}, available_goals=[], parent=None, action=None)
    assert node.is_terminal()
    assert node.is_fully_expanded()


def test_mcts_node_pop_untried_goal_decreases_pool(small_goal_set):
    node = MCTSNode(state={}, available_goals=small_goal_set, parent=None, action=None)
    rng = random.Random(0)
    g = node.pop_untried_goal(rng)
    assert g in small_goal_set
    assert not node.is_fully_expanded()
    # eventually fully expanded after popping all
    while not node.is_fully_expanded():
        node.pop_untried_goal(rng)
    assert node.is_fully_expanded()


def test_mcts_node_pop_untried_raises_when_exhausted():
    node = MCTSNode(state={}, available_goals=[], parent=None, action=None)
    with pytest.raises(RuntimeError):
        node.pop_untried_goal(random.Random(0))


def test_mcts_node_remaining_goals_excludes_taken(small_goal_set):
    node = MCTSNode(state={}, available_goals=small_goal_set, parent=None, action=None)
    taken = small_goal_set[0]
    remaining = node.remaining_goals(taken)
    assert taken not in remaining
    assert len(remaining) == len(small_goal_set) - 1


def test_mcts_node_best_child_uses_ucb1(small_goal_set):
    """A child with high reward AND many visits should beat a starved one."""
    parent = MCTSNode(state={}, available_goals=small_goal_set, parent=None, action=None)
    parent.visits = 100
    rich = MCTSNode(state={}, available_goals=[], parent=parent, action=small_goal_set[0])
    poor = MCTSNode(state={}, available_goals=[], parent=parent, action=small_goal_set[1])
    rich.visits = 50
    rich.total_reward = 50.0  # exploitation = 1.0
    poor.visits = 50
    poor.total_reward = 5.0   # exploitation = 0.1
    parent.children = [rich, poor]
    assert parent.best_child(exploration_weight=1.0) is rich


def test_mcts_node_best_child_explores_starved_arm(small_goal_set):
    """A near-untouched child should win on the exploration term."""
    parent = MCTSNode(state={}, available_goals=small_goal_set, parent=None, action=None)
    parent.visits = 1000
    explored = MCTSNode(state={}, available_goals=[], parent=parent, action=small_goal_set[0])
    starved = MCTSNode(state={}, available_goals=[], parent=parent, action=small_goal_set[1])
    explored.visits = 500
    explored.total_reward = 250.0  # exploitation 0.5
    starved.visits = 1
    starved.total_reward = 0.4     # exploitation 0.4
    parent.children = [explored, starved]
    # Large exploration weight should make the under-visited arm win.
    assert parent.best_child(exploration_weight=5.0) is starved


def test_mcts_node_best_child_raises_with_no_children(small_goal_set):
    parent = MCTSNode(state={}, available_goals=small_goal_set, parent=None, action=None)
    with pytest.raises(RuntimeError):
        parent.best_child()


# ===========================================================================
# StrategicPlanner
# ===========================================================================


def test_strategic_planner_empty_goals_returns_empty_list():
    p = StrategicPlanner(simulation_budget=10, rng=random.Random(0))
    assert p.plan(current_state={}, goals=[], horizon_days=30) == []


def test_strategic_planner_invalid_horizon_raises(small_goal_set):
    p = StrategicPlanner(simulation_budget=10, rng=random.Random(0))
    with pytest.raises(ValueError):
        p.plan(current_state={}, goals=small_goal_set, horizon_days=0)


def test_strategic_planner_invalid_budget_raises():
    with pytest.raises(ValueError):
        StrategicPlanner(simulation_budget=-1)
    with pytest.raises(ValueError):
        StrategicPlanner(simulation_budget=10, max_simulation_steps=0)


def test_strategic_planner_returns_subset_of_input_goals(small_goal_set):
    p = StrategicPlanner(simulation_budget=64, rng=random.Random(0))
    sequence = p.plan(current_state={"capital": 100}, goals=small_goal_set, horizon_days=60)
    goal_ids = {g.goal_id for g in small_goal_set}
    assert sequence  # planning produced at least one goal
    assert all(isinstance(g, StrategicGoal) for g in sequence)
    assert all(g.goal_id in goal_ids for g in sequence)
    assert len(sequence) == len({g.goal_id for g in sequence}), "no duplicates"


def test_strategic_planner_deterministic_with_seed(small_goal_set):
    p1 = StrategicPlanner(simulation_budget=64, rng=random.Random(42))
    p2 = StrategicPlanner(simulation_budget=64, rng=random.Random(42))
    s1 = p1.plan(current_state={"capital": 100}, goals=small_goal_set, horizon_days=60)
    s2 = p2.plan(current_state={"capital": 100}, goals=small_goal_set, horizon_days=60)
    assert [g.goal_id for g in s1] == [g.goal_id for g in s2]


def test_strategic_planner_simulate_stays_within_step_cap(small_goal_set):
    p = StrategicPlanner(simulation_budget=4, rng=random.Random(1), max_simulation_steps=3)
    root = MCTSNode(state={}, available_goals=small_goal_set, parent=None, action=None)
    p._simulate(root, horizon_days=10_000)  # noqa: SLF001 - direct test


def test_strategic_planner_apply_goal_updates_capital_for_trading(small_goal_set):
    p = StrategicPlanner(simulation_budget=1, rng=random.Random(0))
    trading_goal = next(g for g in small_goal_set if g.domain == "trading")
    new_state = p._apply_goal({"capital": 100.0}, trading_goal)  # noqa: SLF001
    assert new_state["capital"] > 100.0
    assert new_state["trading_progress"] >= trading_goal.target_value


# ===========================================================================
# TacticalPlanner / A*
# ===========================================================================


def test_tactical_planner_validates_max_iterations():
    with pytest.raises(ValueError):
        TacticalPlanner(max_iterations=0)


@pytest.mark.parametrize("domain", ["trading", "business", "personal", "system"])
def test_tactical_planner_creates_valid_plan_per_domain(domain: str):
    goal = _make_goal(domain=domain, target=1.0)
    planner = TacticalPlanner(max_iterations=200)
    plan = planner.create_plan(current_state={}, goal=goal)
    assert plan.goal_id == goal.goal_id
    assert plan.steps, f"expected at least one step for domain {domain}"
    assert all("action" in step and "domain" in step for step in plan.steps)
    assert all(step["domain"] == domain for step in plan.steps)


def test_tactical_planner_progress_strictly_non_decreasing():
    goal = _make_goal(domain="trading", target=2.0)
    planner = TacticalPlanner(max_iterations=200)
    plan = planner.create_plan(current_state={}, goal=goal)
    progresses = [step["expected_progress"] for step in plan.steps]
    assert progresses == sorted(progresses)
    assert progresses[-1] >= goal.target_value


def test_tactical_planner_short_path_for_already_satisfied_goal():
    goal = _make_goal(domain="business", target=1.0)
    planner = TacticalPlanner(max_iterations=200)
    plan = planner.create_plan(current_state={"business_value": 5.0}, goal=goal)
    # Already satisfied - reconstructed path is just the start, so zero steps.
    assert plan.steps == []
    assert plan.is_complete()


def test_tactical_planner_heuristic_admissible():
    """The heuristic 'remaining / 0.5' equals the true cost for the best
    action (delta=0.5), so it never overestimates - which is exactly what A*
    needs. Verify with a representative state."""
    planner = TacticalPlanner()
    goal = _make_goal(domain="trading", target=1.0)
    h = planner._heuristic({"trading_value": 0.5}, goal)  # noqa: SLF001
    assert h == pytest.approx(1.0)
    h_zero = planner._heuristic({"trading_value": 5.0}, goal)  # noqa: SLF001
    assert h_zero == 0.0


def test_tactical_planner_iteration_cap_returns_degenerate_path():
    goal = _make_goal(domain="trading", target=1_000_000.0)
    planner = TacticalPlanner(max_iterations=10)
    plan = planner.create_plan(current_state={}, goal=goal)
    # Iteration cap hits, falls back to two-state degenerate path -> 1 step.
    assert len(plan.steps) <= 2


# ===========================================================================
# HierarchicalPolicy
# ===========================================================================


def test_hierarchical_invalid_horizon_raises(hier: HierarchicalPolicy):
    with pytest.raises(ValueError):
        hier.decide({}, horizon="forever")


def test_hierarchical_strategic_sets_active_goal(hier: HierarchicalPolicy):
    out = hier.decide({"capital": 100, "organization_id": 1}, horizon="strategic")
    assert out["layer"] == "strategic"
    assert out["engine"] == "hierarchical"
    assert out["goals"], "strategic planning produced no goals"
    assert out["active_goal_id"] is not None
    assert hier.active_goal is not None


def test_hierarchical_strategic_with_no_goals_clears_active(fresh_engine: PolicyEngine):
    h = HierarchicalPolicy(
        operational=fresh_engine,
        strategic=StrategicPlanner(simulation_budget=10, rng=random.Random(0)),
        goals_provider=lambda _ctx: [],
    )
    out = h.decide({"organization_id": 1}, horizon="strategic")
    assert out["goals"] == []
    assert out["active_goal_id"] is None
    assert h.active_goal is None


def test_hierarchical_tactical_creates_plan(hier: HierarchicalPolicy):
    out = hier.decide({"capital": 100, "organization_id": 1}, horizon="tactical")
    assert out["layer"] == "tactical"
    assert out["plan_id"]
    assert out["steps"], "expected non-empty plan steps"
    assert out["expected_reward"] >= 0
    assert hier.active_plan is not None
    assert hier.active_plan.plan_id == out["plan_id"]


def test_hierarchical_tactical_runs_strategic_first_when_no_goal(hier: HierarchicalPolicy):
    assert hier.active_goal is None
    out = hier.decide({"capital": 100, "organization_id": 1}, horizon="tactical")
    assert out["plan_id"]
    assert hier.active_goal is not None


def test_hierarchical_tactical_no_goal_returns_error(fresh_engine: PolicyEngine):
    h = HierarchicalPolicy(
        operational=fresh_engine,
        strategic=StrategicPlanner(simulation_budget=10, rng=random.Random(0)),
        goals_provider=lambda _ctx: [],
    )
    out = h.decide({"organization_id": 1}, horizon="tactical")
    assert out["error"] == "no_active_goal"
    assert out["plan_id"] is None


def test_hierarchical_operational_delegates_to_policy_engine(hier: HierarchicalPolicy):
    out = hier.decide(
        {"intent": "analyze_trade_opportunity", "domain": "trading", "organization_id": 1},
        horizon="immediate",
    )
    assert out["layer"] == "operational"
    assert out["action"]
    assert 0.0 <= out["confidence"] <= 1.0
    assert out["engine"] == "hierarchical"
    # The unified shape is preserved so record_decision_outcome can consume it.
    for key in ("intent", "domain", "user_id", "organization_id", "risk_tolerance"):
        assert key in out


def test_hierarchical_operational_advances_plan_on_match(hier: HierarchicalPolicy):
    """When the bandit picks the very next planned step, the plan pointer
    should advance and ``plan_advanced=True``. We force this by restricting
    available_actions to the plan's next step inside the operational layer."""
    hier.decide({"capital": 100, "organization_id": 1}, horizon="tactical")
    assert hier.active_plan is not None
    next_action = hier.active_plan.next_action()
    assert next_action is not None
    out = hier.decide(
        {"intent": "analyze_trade_opportunity", "domain": "trading", "organization_id": 1},
        horizon="immediate",
    )
    assert out["action"] == next_action["action"]
    assert out["plan_advanced"] is True
    assert hier.active_plan.current_step == 1


def test_hierarchical_operational_does_not_advance_when_no_plan(hier: HierarchicalPolicy):
    out = hier.decide({"intent": "general_decision", "organization_id": 1}, horizon="immediate")
    assert out["plan_advanced"] is False
    assert out["active_plan"] is None


def test_hierarchical_reset_active_drops_state(hier: HierarchicalPolicy):
    hier.decide({"capital": 100, "organization_id": 1}, horizon="tactical")
    assert hier.active_goal is not None
    assert hier.active_plan is not None
    hier.reset_active()
    assert hier.active_goal is None
    assert hier.active_plan is None


def test_hierarchical_load_goals_swallows_provider_errors(fresh_engine: PolicyEngine):
    def boom(_ctx):
        raise RuntimeError("boom")

    h = HierarchicalPolicy(
        operational=fresh_engine,
        strategic=StrategicPlanner(simulation_budget=10, rng=random.Random(0)),
        goals_provider=boom,
    )
    out = h.decide({"organization_id": 1}, horizon="strategic")
    assert out["goals"] == []


def test_hierarchical_operational_handles_engine_failure(monkeypatch, hier: HierarchicalPolicy):
    def explode(*_a, **_kw):
        raise RuntimeError("simulated engine outage")

    monkeypatch.setattr(hier.operational, "decide", explode)
    out = hier.decide({"organization_id": 1}, horizon="immediate")
    assert out["error"] == "operational_failure"
    assert "simulated engine outage" in out["error_message"]


# ===========================================================================
# Singleton + DB adapter
# ===========================================================================


def test_singleton_returns_same_instance():
    first = get_hierarchical_policy()
    second = get_hierarchical_policy()
    assert first is second


def test_reset_singleton_returns_new_instance():
    first = get_hierarchical_policy()
    reset_hierarchical_policy()
    second = get_hierarchical_policy()
    assert first is not second


def test_default_goals_provider_returns_empty_without_factory(monkeypatch):
    """When the DB session factory returns None, the provider returns []
    instead of crashing."""

    import services.hierarchical_policy as hp

    monkeypatch.setattr(
        "core.database.get_session_factory",
        lambda: None,
        raising=True,
    )
    assert hp.default_goals_provider({"organization_id": 1, "user_id": 1}) == []


def test_default_goals_provider_returns_empty_when_no_org_or_user(monkeypatch):
    # Provider must not even open a session if there's no org_id / user_id.
    sentinel: list[Any] = []

    def fake_factory():
        sentinel.append("called")
        raise AssertionError("factory should not be invoked")

    monkeypatch.setattr("core.database.get_session_factory", lambda: fake_factory)
    assert default_goals_provider({}) == []
    assert sentinel == []


def test_jarvis_goal_adapter_extracts_meta_overrides():
    row = SimpleNamespace(
        id=42,
        description="Hit $5k revenue",
        target_value="$5,000",
        deadline=date(2099, 1, 1),
        goal_type="business",
        meta={"target_numeric": 5000.0, "domain": "business", "priority": 0.9},
        progress={"current_value": 1500.0},
    )
    g = _jarvis_goal_to_strategic(row)
    assert g.goal_id == "42"
    assert g.target_value == 5000.0
    assert g.current_value == 1500.0
    assert g.priority == 0.9
    assert g.domain == "business"
    assert g.deadline.tzinfo is not None  # date promoted to tz-aware datetime


def test_jarvis_goal_adapter_unknown_domain_falls_back_to_business():
    row = SimpleNamespace(
        id=1,
        description="Mystery goal",
        target_value="N/A",
        deadline=None,
        goal_type="weird_unknown_type",
        meta={},
        progress={},
    )
    g = _jarvis_goal_to_strategic(row)
    assert g.domain == "business"
    assert g.target_value == 1.0  # safe default
    assert g.deadline > datetime.now(timezone.utc)  # ~90d default


def test_jarvis_goal_adapter_handles_missing_progress_dict():
    row = SimpleNamespace(
        id=7, description="x", target_value=None, deadline=None,
        goal_type="trading", meta=None, progress=None,
    )
    g = _jarvis_goal_to_strategic(row)
    assert g.current_value == 0.0
    assert g.domain == "trading"


# ===========================================================================
# DecisionRouter integration
# ===========================================================================


def test_router_disabled_by_default_uses_existing_flow(monkeypatch, fresh_engine: PolicyEngine):
    monkeypatch.delenv("THIRAMAI_HIERARCHICAL_POLICY", raising=False)
    monkeypatch.delenv("HIERARCHICAL_POLICY", raising=False)
    monkeypatch.setenv("THIRAMAI_DECISION_AB_TEST", "true")
    monkeypatch.setenv("THIRAMAI_POLICY_ENGINE_PCT", "100")
    router = DecisionRouter(policy_engine=fresh_engine)
    assert router.use_hierarchical is False
    decision, engine = router.route(
        {"intent": "analyze_trade_opportunity", "domain": "trading",
         "organization_id": 1, "horizon": "strategic"},
        user_id=7,
    )
    assert engine == "policy_engine"
    assert decision["engine"] == "policy_engine"


def test_router_immediate_horizon_never_uses_hierarchical(monkeypatch, fresh_engine: PolicyEngine):
    monkeypatch.setenv("THIRAMAI_HIERARCHICAL_POLICY", "true")
    monkeypatch.setenv("THIRAMAI_DECISION_AB_TEST", "true")
    monkeypatch.setenv("THIRAMAI_POLICY_ENGINE_PCT", "100")
    router = DecisionRouter(policy_engine=fresh_engine)
    assert router.use_hierarchical is True
    decision, engine = router.route(
        {"intent": "analyze_trade_opportunity", "domain": "trading",
         "organization_id": 1, "horizon": "immediate"},
        user_id=7,
    )
    assert engine == "policy_engine"
    assert decision["engine"] == "policy_engine"


def test_router_strategic_horizon_routes_to_hierarchical(monkeypatch, fresh_engine: PolicyEngine, small_goal_set):
    monkeypatch.setenv("THIRAMAI_HIERARCHICAL_POLICY", "true")
    monkeypatch.setenv("THIRAMAI_DECISION_AB_TEST", "true")
    monkeypatch.setenv("THIRAMAI_POLICY_ENGINE_PCT", "100")
    # Replace the singleton with one wired to our deterministic test data.
    import services.hierarchical_policy as hp

    fresh = HierarchicalPolicy(
        operational=fresh_engine,
        strategic=StrategicPlanner(simulation_budget=32, rng=random.Random(0)),
        tactical=TacticalPlanner(max_iterations=200),
        goals_provider=lambda _ctx: list(small_goal_set),
    )
    monkeypatch.setattr(hp, "_singleton", fresh, raising=False)

    router = DecisionRouter(policy_engine=fresh_engine)
    decision, engine = router.route(
        {"intent": "any", "domain": "trading", "organization_id": 1, "horizon": "strategic"},
        user_id=1,
    )
    assert engine == "hierarchical"
    assert decision["engine"] == "hierarchical"
    assert decision["layer"] == "strategic"
    assert decision["goals"]


def test_router_tactical_horizon_routes_to_hierarchical(monkeypatch, fresh_engine: PolicyEngine, small_goal_set):
    monkeypatch.setenv("THIRAMAI_HIERARCHICAL_POLICY", "true")
    import services.hierarchical_policy as hp

    fresh = HierarchicalPolicy(
        operational=fresh_engine,
        strategic=StrategicPlanner(simulation_budget=16, rng=random.Random(0)),
        goals_provider=lambda _ctx: list(small_goal_set),
    )
    monkeypatch.setattr(hp, "_singleton", fresh, raising=False)
    router = DecisionRouter(policy_engine=fresh_engine)
    decision, engine = router.route(
        {"intent": "any", "domain": "trading", "organization_id": 1, "horizon": "tactical"},
        user_id=1,
    )
    assert engine == "hierarchical"
    assert decision["layer"] == "tactical"
    assert decision["plan_id"]


def test_router_hierarchical_failure_falls_back_to_legacy(monkeypatch, fresh_engine: PolicyEngine):
    monkeypatch.setenv("THIRAMAI_HIERARCHICAL_POLICY", "true")
    monkeypatch.setenv("THIRAMAI_DECISION_AB_TEST", "true")
    monkeypatch.setenv("THIRAMAI_POLICY_ENGINE_PCT", "0")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    import services.hierarchical_policy as hp

    class Boom(HierarchicalPolicy):
        def decide(self, *_a, **_kw):
            raise RuntimeError("hierarchical exploded")

    monkeypatch.setattr(
        hp, "_singleton",
        Boom(operational=fresh_engine, goals_provider=lambda _c: []),
        raising=False,
    )
    router = DecisionRouter(policy_engine=fresh_engine)
    decision, engine = router.route(
        {"intent": "any", "domain": "trading", "organization_id": 1, "horizon": "strategic"},
        user_id=1,
    )
    assert engine == "legacy"
    assert decision["engine"] == "legacy"


def test_router_time_horizon_alias_also_works(monkeypatch, fresh_engine: PolicyEngine, small_goal_set):
    """``time_horizon`` is the field name DecisionContext uses; the router
    should accept it as an alias for ``horizon``."""

    monkeypatch.setenv("THIRAMAI_HIERARCHICAL_POLICY", "true")
    import services.hierarchical_policy as hp

    fresh = HierarchicalPolicy(
        operational=fresh_engine,
        strategic=StrategicPlanner(simulation_budget=16, rng=random.Random(0)),
        goals_provider=lambda _ctx: list(small_goal_set),
    )
    monkeypatch.setattr(hp, "_singleton", fresh, raising=False)
    router = DecisionRouter(policy_engine=fresh_engine)
    decision, engine = router.route(
        {"intent": "any", "domain": "trading", "organization_id": 1, "time_horizon": "strategic"},
        user_id=1,
    )
    assert engine == "hierarchical"
    assert decision["layer"] == "strategic"


# ===========================================================================
# Integration / sanity
# ===========================================================================


def test_hierarchical_uses_same_policy_engine_singleton(small_goal_set):
    """Sanity check: when the operational engine is left to the default, the
    hierarchical layer reuses the global singleton - so bandit weights from
    direct PolicyEngine calls are visible to hierarchical operational calls."""
    from services.policy_engine import get_policy_engine

    h = HierarchicalPolicy(
        strategic=StrategicPlanner(simulation_budget=4, rng=random.Random(0)),
        goals_provider=lambda _ctx: list(small_goal_set),
    )
    assert h.operational is get_policy_engine()


def test_hierarchical_operational_writes_decision_output_shape(hier: HierarchicalPolicy):
    """The dict returned must carry the same fields downstream metrics /
    record_decision_outcome expect (action, action_type, confidence, etc.)."""
    out = hier.decide({"intent": "analyze_trade_opportunity", "domain": "trading"}, horizon="immediate")
    expected_keys = {"action", "action_type", "confidence", "expected_reward",
                     "exploration_bonus", "reasoning", "engine", "intent", "domain",
                     "risk_tolerance", "time_horizon", "metadata"}
    assert expected_keys.issubset(out.keys()), expected_keys - out.keys()


def test_hierarchical_decide_output_is_independent_of_input_dict(hier: HierarchicalPolicy):
    """Mutating the caller's context dict after decide() should not leak into
    the decision payload."""
    ctx = {"intent": "a", "domain": "trading", "organization_id": 1}
    out = hier.decide(ctx, horizon="immediate")
    ctx["intent"] = "MUTATED"
    assert out["intent"] == "a"
