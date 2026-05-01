"""3-layer hierarchical policy: strategic (MCTS) + tactical (A*) + operational (LinUCB).

Layers
------
* **Strategic** - long-horizon goal prioritisation via Monte Carlo Tree Search
  (UCB1 selection, random rollout simulation, classic backpropagation).
* **Tactical** - A* search over a small action-space graph that turns the
  selected strategic goal into an executable step sequence.
* **Operational** - delegates to the existing
  :class:`services.policy_engine.PolicyEngine` (LinUCB contextual bandit) for
  immediate action selection. The LinUCB feature schema, persistence, and
  ``LearningLog`` writes are reused unchanged.

Integration with the rest of the brain stack:

* The strategic / tactical layers are invoked through
  :class:`services.decision_router.DecisionRouter` when the request carries a
  ``horizon`` of ``"strategic"`` or ``"tactical"`` and the
  ``THIRAMAI_HIERARCHICAL_POLICY`` flag is on.
* The operational layer is the same singleton bandit used by the existing
  routes; nothing changes for ``horizon="immediate"`` (existing A/B test split
  between PolicyEngine and the legacy decision brain still applies).
* The default goals provider reads :class:`core.db.models.JarvisGoal` rows.
  ``JarvisGoal.target_value`` is a ``String(512)`` and there is no ``domain``
  / ``priority`` / ``current_value`` column, so the adapter parses what it can
  out of ``goal.meta`` / ``goal.progress`` and falls back to safe defaults.
* All randomness flows through an injected :class:`random.Random` instance so
  tests are deterministic without having to monkey-patch ``numpy.random``.
"""

from __future__ import annotations

import logging
import math
import random
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from heapq import heappop, heappush
from typing import Any, Callable, Iterable

from services.policy_engine import DecisionContext, PolicyEngine, get_policy_engine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


_KNOWN_DOMAINS: frozenset[str] = frozenset({"trading", "business", "personal", "system"})
_MAX_HORIZON_DAYS_FOR_URGENCY = 90
_DEFAULT_PROGRESS_PER_STEP = 0.5  # used by the A* heuristic


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class StrategicGoal:
    """Long-term goal the strategic planner can choose to pursue."""

    goal_id: str
    description: str
    domain: str  # "trading" | "business" | "personal" | "system"
    target_value: float
    current_value: float
    deadline: datetime
    priority: float = 0.5  # 0 - 1
    dependencies: list[str] = field(default_factory=list)

    def progress(self) -> float:
        """Fraction of ``target_value`` already realised, clamped to ``[0, 1]``.

        ``target_value <= 0`` is treated as 'already satisfied' (1.0) rather
        than raising, so a malformed row from the DB cannot crash a planner
        invocation downstream.
        """
        try:
            target = float(self.target_value)
        except (TypeError, ValueError):
            return 1.0
        if target <= 0:
            return 1.0
        try:
            current = float(self.current_value)
        except (TypeError, ValueError):
            current = 0.0
        return max(0.0, min(1.0, current / target))

    def urgency(self) -> float:
        """How urgent the goal is, in ``[0, 1]``.

        Linear ramp from 0 (deadline >= 90 days away) to 1 (deadline <= now).
        Naive (tz-less) datetimes are coerced to UTC before comparison so
        ``JarvisGoal.deadline`` (a ``date``) doesn't crash arithmetic.
        """
        deadline = self.deadline
        if isinstance(deadline, date) and not isinstance(deadline, datetime):
            deadline = datetime(deadline.year, deadline.month, deadline.day, tzinfo=timezone.utc)
        elif isinstance(deadline, datetime) and deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        days_left = (deadline - _now_utc()).total_seconds() / 86_400.0
        if days_left <= 0:
            return 1.0
        return max(0.0, 1.0 - (days_left / _MAX_HORIZON_DAYS_FOR_URGENCY))


@dataclass
class TacticalPlan:
    """A concrete step sequence pursuing one ``StrategicGoal``."""

    plan_id: str
    goal_id: str
    steps: list[dict[str, Any]]
    estimated_duration: timedelta
    estimated_cost: float
    estimated_reward: float
    current_step: int = 0

    def next_action(self) -> dict[str, Any] | None:
        if self.current_step >= len(self.steps):
            return None
        return self.steps[self.current_step]

    def is_complete(self) -> bool:
        return self.current_step >= len(self.steps)


# ---------------------------------------------------------------------------
# MCTS node + strategic planner
# ---------------------------------------------------------------------------


class MCTSNode:
    """Node in the strategic-planner MCTS tree.

    ``action`` holds the :class:`StrategicGoal` that was *taken to reach this
    node from its parent* (root has ``action=None``).
    """

    __slots__ = ("state", "available_goals", "parent", "action", "children", "visits", "total_reward", "_untried")

    def __init__(
        self,
        state: dict[str, Any],
        available_goals: list[StrategicGoal],
        parent: "MCTSNode | None",
        action: StrategicGoal | None,
    ) -> None:
        self.state: dict[str, Any] = state
        self.available_goals: list[StrategicGoal] = list(available_goals)
        self.parent: MCTSNode | None = parent
        self.action: StrategicGoal | None = action
        self.children: list[MCTSNode] = []
        self.visits: int = 0
        self.total_reward: float = 0.0
        self._untried: list[StrategicGoal] = list(available_goals)

    # -- structural queries ---------------------------------------------

    def is_terminal(self) -> bool:
        return not self.available_goals

    def is_fully_expanded(self) -> bool:
        return not self._untried

    def add_child(self, child: "MCTSNode") -> None:
        self.children.append(child)

    # -- expansion / selection ------------------------------------------

    def pop_untried_goal(self, rng: random.Random) -> StrategicGoal:
        """Remove and return one untried goal (uniform random)."""
        if not self._untried:
            raise RuntimeError("pop_untried_goal called on fully-expanded node")
        idx = rng.randrange(len(self._untried))
        return self._untried.pop(idx)

    def remaining_goals(self, taken: StrategicGoal) -> list[StrategicGoal]:
        return [g for g in self.available_goals if g.goal_id != taken.goal_id]

    def best_child(self, exploration_weight: float = math.sqrt(2)) -> "MCTSNode":
        """UCB1 child selection.

        Children are guaranteed to have ``visits >= 1`` because each child is
        simulated exactly once at the moment it is created (see
        :meth:`StrategicPlanner._expand`), so the ``log(parent.visits)/visits``
        term is well-defined. The parent's ``visits`` is at least 1 by the
        time this method runs.
        """
        if not self.children:
            raise RuntimeError("best_child called on a node with no children")
        parent_visits = max(self.visits, 1)
        best: MCTSNode | None = None
        best_score = -math.inf
        for child in self.children:
            visits = max(child.visits, 1)
            exploitation = child.total_reward / visits
            exploration = exploration_weight * math.sqrt(math.log(parent_visits) / visits)
            score = exploitation + exploration
            if score > best_score:
                best_score = score
                best = child
        assert best is not None
        return best


class StrategicPlanner:
    """Long-horizon planner: which goals should we pursue next?"""

    def __init__(
        self,
        simulation_budget: int = 1000,
        *,
        rng: random.Random | None = None,
        max_simulation_steps: int = 32,
    ) -> None:
        if simulation_budget < 0:
            raise ValueError("simulation_budget must be non-negative")
        if max_simulation_steps <= 0:
            raise ValueError("max_simulation_steps must be positive")
        self.simulation_budget = int(simulation_budget)
        self.max_simulation_steps = int(max_simulation_steps)
        self._rng = rng or random.Random()

    # -- public entry point ---------------------------------------------

    def plan(
        self,
        current_state: dict[str, Any],
        goals: list[StrategicGoal],
        horizon_days: int = 90,
    ) -> list[StrategicGoal]:
        """Return a prioritised goal sequence; empty list if nothing to plan."""
        if not goals:
            return []
        if horizon_days <= 0:
            raise ValueError("horizon_days must be positive")

        root = MCTSNode(state=dict(current_state), available_goals=list(goals), parent=None, action=None)

        for _ in range(self.simulation_budget):
            node = self._select(root)
            if not node.is_terminal() and not node.is_fully_expanded():
                node = self._expand(node)
            reward = self._simulate(node, horizon_days)
            self._backpropagate(node, reward)

        sequence = self._extract_best_path(root)
        logger.info("strategic.plan budget=%d goals_in=%d sequence_out=%d", self.simulation_budget, len(goals), len(sequence))
        return sequence

    # -- MCTS phases ----------------------------------------------------

    def _select(self, node: MCTSNode) -> MCTSNode:
        """Walk down the tree using UCB1 until we hit a node that can be expanded."""
        while not node.is_terminal() and node.is_fully_expanded() and node.children:
            node = node.best_child()
        return node

    def _expand(self, node: MCTSNode) -> MCTSNode:
        goal = node.pop_untried_goal(self._rng)
        new_state = self._apply_goal(node.state, goal)
        child = MCTSNode(
            state=new_state,
            available_goals=node.remaining_goals(goal),
            parent=node,
            action=goal,
        )
        node.add_child(child)
        return child

    def _simulate(self, node: MCTSNode, horizon_days: int) -> float:
        state = dict(node.state)
        goals = list(node.available_goals)
        total_reward = 0.0
        days = 0
        steps = 0
        while goals and days < horizon_days and steps < self.max_simulation_steps:
            goal = self._rng.choice(goals)
            success_prob = self._estimate_success_probability(state, goal)
            if self._rng.random() < success_prob:
                total_reward += float(goal.priority) * float(goal.target_value)
                state = self._apply_goal(state, goal)
                goals = [g for g in goals if g.goal_id != goal.goal_id]
            days += self._rng.randint(7, 30)
            steps += 1
        return total_reward

    def _backpropagate(self, node: MCTSNode | None, reward: float) -> None:
        while node is not None:
            node.visits += 1
            node.total_reward += reward
            node = node.parent

    def _extract_best_path(self, root: MCTSNode) -> list[StrategicGoal]:
        """Greedy descent on most-visited child.

        Stops on (a) terminal node, OR (b) a node with no children left to
        descend into - the latter happens when the simulation budget ran out
        before a deeper subtree was fully explored. Without that guard, a
        ``max([])`` call would explode here.
        """
        path: list[StrategicGoal] = []
        node = root
        while not node.is_terminal() and node.children:
            best = max(node.children, key=lambda c: c.visits)
            assert best.action is not None  # only the root has action=None
            path.append(best.action)
            node = best
        return path

    # -- model hooks ----------------------------------------------------

    def _estimate_success_probability(self, state: dict[str, Any], goal: StrategicGoal) -> float:
        base = 0.7
        progress_bonus = goal.progress() * 0.2
        urgency_penalty = goal.urgency() * 0.1
        return max(0.0, min(1.0, base + progress_bonus - urgency_penalty))

    def _apply_goal(self, state: dict[str, Any], goal: StrategicGoal) -> dict[str, Any]:
        new_state = dict(state)
        if goal.domain == "trading" and "capital" in new_state:
            try:
                new_state["capital"] = float(new_state["capital"]) * (1 + float(goal.target_value) * 0.01)
            except (TypeError, ValueError):
                pass
        progress_key = f"{goal.domain}_progress"
        try:
            new_state[progress_key] = float(new_state.get(progress_key, 0.0)) + float(goal.target_value)
        except (TypeError, ValueError):
            new_state[progress_key] = float(goal.target_value or 0.0)
        return new_state


# ---------------------------------------------------------------------------
# Tactical planner (A*)
# ---------------------------------------------------------------------------


class TacticalPlanner:
    """A*-based step sequencer for one ``StrategicGoal``.

    The state graph is intentionally tiny - each domain offers a fixed set of
    actions that nudge a single ``<domain>_value`` scalar toward
    ``goal.target_value``. This is enough for the operational layer to have a
    short ordered queue of actions to consider.
    """

    # Counter used as a tiebreaker for the priority queue so that two states
    # with identical f-scores never have to be compared with ``<`` (dicts
    # aren't orderable). Module-level so multiple instances share the seq.
    _seq_lock = threading.Lock()
    _seq = 0

    def __init__(self, *, max_iterations: int = 1000) -> None:
        if max_iterations <= 0:
            raise ValueError("max_iterations must be positive")
        self.max_iterations = int(max_iterations)

    @classmethod
    def _next_seq(cls) -> int:
        with cls._seq_lock:
            cls._seq += 1
            return cls._seq

    # -- public --------------------------------------------------------

    def create_plan(self, current_state: dict[str, Any], goal: StrategicGoal) -> TacticalPlan:
        path = self._astar_search(dict(current_state), goal)
        steps = self._path_to_steps(path, goal)
        plan = TacticalPlan(
            plan_id=f"plan_{goal.goal_id}_{int(_now_utc().timestamp() * 1000)}",
            goal_id=goal.goal_id,
            steps=steps,
            estimated_duration=self._estimate_duration(steps),
            estimated_cost=self._estimate_cost(steps),
            estimated_reward=float(goal.target_value) * float(goal.priority),
            current_step=0,
        )
        logger.info("tactical.create_plan goal=%s steps=%d", goal.goal_id, len(steps))
        return plan

    # -- A* core -------------------------------------------------------

    def _astar_search(self, start_state: dict[str, Any], goal: StrategicGoal) -> list[dict[str, Any]]:
        # Start state must be hashable - canonicalise the same way every node does.
        start_key = self._state_hash(start_state)
        open_set: list[tuple[float, int, dict[str, Any]]] = []
        heappush(open_set, (0.0, self._next_seq(), start_state))
        came_from: dict[tuple, dict[str, Any]] = {}
        g_score: dict[tuple, float] = {start_key: 0.0}
        iterations = 0

        while open_set and iterations < self.max_iterations:
            iterations += 1
            _, _, current = heappop(open_set)
            current_key = self._state_hash(current)

            if self._is_goal_state(current, goal):
                return self._reconstruct_path(came_from, current)

            for neighbor in self._get_neighbors(current, goal):
                neighbor_key = self._state_hash(neighbor)
                tentative_g = g_score[current_key] + self._cost(current, neighbor)
                if neighbor_key not in g_score or tentative_g < g_score[neighbor_key]:
                    came_from[neighbor_key] = current
                    g_score[neighbor_key] = tentative_g
                    f_score = tentative_g + self._heuristic(neighbor, goal)
                    heappush(open_set, (f_score, self._next_seq(), neighbor))

        # Either the open set drained or we hit the iteration cap. Return a
        # degenerate two-point path so the caller still gets a plan it can
        # downgrade gracefully.
        logger.warning("tactical.astar.no_path goal=%s iterations=%d", goal.goal_id, iterations)
        return [start_state, self._goal_state(goal)]

    # -- A* helpers ----------------------------------------------------

    def _state_hash(self, state: dict[str, Any]) -> tuple:
        return tuple(sorted((str(k), v) for k, v in state.items()))

    def _is_goal_state(self, state: dict[str, Any], goal: StrategicGoal) -> bool:
        key = f"{goal.domain}_value"
        try:
            return float(state.get(key, 0)) >= float(goal.target_value)
        except (TypeError, ValueError):
            return False

    def _get_neighbors(self, state: dict[str, Any], goal: StrategicGoal) -> list[dict[str, Any]]:
        if goal.domain == "trading":
            return self._trading_actions(state)
        if goal.domain == "business":
            return self._business_actions(state)
        if goal.domain == "personal":
            return self._personal_actions(state)
        return self._system_actions(state)

    @staticmethod
    def _make_neighbor(state: dict[str, Any], action: str, value_key: str, delta: float) -> dict[str, Any]:
        new = dict(state)
        new["action"] = action
        try:
            new[value_key] = float(new.get(value_key, 0.0)) + float(delta)
        except (TypeError, ValueError):
            new[value_key] = float(delta)
        return new

    def _trading_actions(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            self._make_neighbor(state, "analyze_market", "trading_value", 0.1),
            self._make_neighbor(state, "execute_trade", "trading_value", 0.5),
            self._make_neighbor(state, "adjust_position", "trading_value", 0.3),
        ]

    def _business_actions(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            self._make_neighbor(state, "market_research", "business_value", 0.2),
            self._make_neighbor(state, "launch_campaign", "business_value", 0.4),
            self._make_neighbor(state, "optimize_pricing", "business_value", 0.3),
        ]

    def _personal_actions(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            self._make_neighbor(state, "skill_learning", "personal_value", 0.3),
            self._make_neighbor(state, "health_focus", "personal_value", 0.2),
            self._make_neighbor(state, "network_building", "personal_value", 0.4),
        ]

    def _system_actions(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            self._make_neighbor(state, "monitor", "system_value", 0.2),
            self._make_neighbor(state, "optimize", "system_value", 0.3),
            self._make_neighbor(state, "scale", "system_value", 0.4),
        ]

    def _cost(self, state1: dict[str, Any], state2: dict[str, Any]) -> float:
        return 1.0

    def _heuristic(self, state: dict[str, Any], goal: StrategicGoal) -> float:
        key = f"{goal.domain}_value"
        try:
            current = float(state.get(key, 0))
            target = float(goal.target_value)
        except (TypeError, ValueError):
            return 0.0
        remaining = max(0.0, target - current)
        return remaining / _DEFAULT_PROGRESS_PER_STEP

    def _reconstruct_path(self, came_from: dict[tuple, dict[str, Any]], end: dict[str, Any]) -> list[dict[str, Any]]:
        path = [end]
        current_key = self._state_hash(end)
        while current_key in came_from:
            prev = came_from[current_key]
            path.append(prev)
            current_key = self._state_hash(prev)
        path.reverse()
        return path

    def _goal_state(self, goal: StrategicGoal) -> dict[str, Any]:
        try:
            target = float(goal.target_value)
        except (TypeError, ValueError):
            target = 0.0
        return {f"{goal.domain}_value": target, "action": "reach_goal"}

    def _path_to_steps(self, path: list[dict[str, Any]], goal: StrategicGoal) -> list[dict[str, Any]]:
        if len(path) <= 1:
            return []
        steps: list[dict[str, Any]] = []
        for state in path[1:]:
            steps.append(
                {
                    "action": state.get("action", "proceed"),
                    "domain": goal.domain,
                    "expected_progress": float(state.get(f"{goal.domain}_value", 0.0)),
                }
            )
        return steps

    def _estimate_duration(self, steps: list[dict[str, Any]]) -> timedelta:
        return timedelta(days=max(0, len(steps)) * 2)

    def _estimate_cost(self, steps: list[dict[str, Any]]) -> float:
        return float(len(steps)) * 1000.0


# ---------------------------------------------------------------------------
# Default goals provider (JarvisGoal -> StrategicGoal)
# ---------------------------------------------------------------------------


GoalsProvider = Callable[[dict[str, Any]], list[StrategicGoal]]


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _jarvis_goal_to_strategic(row: Any) -> StrategicGoal:
    """Best-effort adapter from a ``JarvisGoal`` ORM row to a ``StrategicGoal``.

    ``JarvisGoal.target_value`` is a free-form string; ``meta`` and
    ``progress`` are the JSON columns that carry the numeric / categorical
    information the strategic layer actually wants.
    """
    meta = dict(getattr(row, "meta", None) or {})
    progress = dict(getattr(row, "progress", None) or {})
    raw_target = meta.get("target_numeric", getattr(row, "target_value", None))
    target = _coerce_float(raw_target, 1.0)
    current = _coerce_float(progress.get("current_value", progress.get("current", 0.0)), 0.0)
    domain_raw = str(meta.get("domain", getattr(row, "goal_type", None) or "business")).strip().lower()
    domain = domain_raw if domain_raw in _KNOWN_DOMAINS else "business"
    priority = max(0.0, min(1.0, _coerce_float(meta.get("priority", 0.5), 0.5)))
    deadline_raw = getattr(row, "deadline", None)
    if deadline_raw is None:
        deadline = _now_utc() + timedelta(days=90)
    elif isinstance(deadline_raw, datetime):
        deadline = deadline_raw if deadline_raw.tzinfo else deadline_raw.replace(tzinfo=timezone.utc)
    elif isinstance(deadline_raw, date):
        deadline = datetime(deadline_raw.year, deadline_raw.month, deadline_raw.day, tzinfo=timezone.utc)
    else:
        deadline = _now_utc() + timedelta(days=90)
    deps_raw = meta.get("dependencies") or []
    dependencies = [str(d) for d in deps_raw] if isinstance(deps_raw, Iterable) else []
    return StrategicGoal(
        goal_id=str(getattr(row, "id", "") or meta.get("goal_id") or ""),
        description=str(getattr(row, "description", "") or meta.get("description", "")),
        domain=domain,
        target_value=target,
        current_value=current,
        deadline=deadline,
        priority=priority,
        dependencies=dependencies,
    )


def default_goals_provider(context: dict[str, Any]) -> list[StrategicGoal]:
    """Read active goals from ``jarvis_goals`` for the request's organisation.

    Returns ``[]`` whenever the DB session factory or the ORM model is
    unavailable - the strategic planner short-circuits on an empty list, so
    callers never have to special-case 'no DB'.
    """
    try:
        from sqlalchemy import select
        from core.database import get_session_factory
        from core.db.models import JarvisGoal
    except Exception as exc:  # pragma: no cover - import is environment-dependent
        logger.debug("hierarchical.goals_provider unavailable: %s", exc)
        return []

    factory = get_session_factory()
    if factory is None:
        return []

    org_id = context.get("organization_id")
    user_id = context.get("user_id")
    if org_id is None and user_id is None:
        return []

    try:
        with factory() as session:
            stmt = select(JarvisGoal).where(JarvisGoal.status == "open")
            if org_id is not None:
                stmt = stmt.where(JarvisGoal.organization_id == int(org_id))
            elif user_id is not None:
                stmt = stmt.where(JarvisGoal.user_id == int(user_id))
            rows = session.scalars(stmt.limit(50)).all()
    except Exception as exc:
        logger.warning("hierarchical.goals_provider db_error: %s", exc)
        return []

    return [_jarvis_goal_to_strategic(r) for r in rows]


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------


_VALID_HORIZONS = ("immediate", "tactical", "strategic")


class HierarchicalPolicy:
    """Strategic + tactical + operational decision orchestrator."""

    def __init__(
        self,
        *,
        operational: PolicyEngine | None = None,
        strategic: StrategicPlanner | None = None,
        tactical: TacticalPlanner | None = None,
        goals_provider: GoalsProvider | None = None,
    ) -> None:
        self.strategic = strategic or StrategicPlanner(simulation_budget=1000)
        self.tactical = tactical or TacticalPlanner()
        self.operational: PolicyEngine = operational or get_policy_engine()
        self._goals_provider: GoalsProvider = goals_provider or default_goals_provider

        self._lock = threading.Lock()
        self.active_goal: StrategicGoal | None = None
        self.active_plan: TacticalPlan | None = None

        logger.info(
            "HierarchicalPolicy ready operational=%s strategic_budget=%d tactical_iter=%d",
            type(self.operational).__name__,
            self.strategic.simulation_budget,
            self.tactical.max_iterations,
        )

    # -- public --------------------------------------------------------

    def decide(self, context: dict[str, Any], horizon: str = "immediate") -> dict[str, Any]:
        h = (horizon or "immediate").strip().lower()
        if h not in _VALID_HORIZONS:
            raise ValueError(f"horizon must be one of {_VALID_HORIZONS}, got {horizon!r}")
        ctx = dict(context or {})
        if h == "strategic":
            return self._strategic_decision(ctx)
        if h == "tactical":
            return self._tactical_decision(ctx)
        return self._operational_decision(ctx)

    def reset_active(self) -> None:
        """Drop the active goal / plan; useful for tests and operator commands."""
        with self._lock:
            self.active_goal = None
            self.active_plan = None

    # -- strategic -----------------------------------------------------

    def _strategic_decision(self, context: dict[str, Any]) -> dict[str, Any]:
        goals = self._load_goals(context)
        sequence = self.strategic.plan(current_state=context, goals=goals, horizon_days=90)
        with self._lock:
            self.active_goal = sequence[0] if sequence else None
        active_desc = self.active_goal.description if self.active_goal else None
        return {
            "layer": "strategic",
            "engine": "hierarchical",
            "horizon": "strategic",
            "horizon_days": 90,
            "goals": [g.description for g in sequence],
            "goal_ids": [g.goal_id for g in sequence],
            "active_goal": active_desc,
            "active_goal_id": self.active_goal.goal_id if self.active_goal else None,
            "timestamp": _now_utc().isoformat(),
        }

    # -- tactical ------------------------------------------------------

    def _tactical_decision(self, context: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            current_goal = self.active_goal

        if current_goal is None:
            self._strategic_decision(context)
            with self._lock:
                current_goal = self.active_goal

        if current_goal is None:
            return {
                "layer": "tactical",
                "engine": "hierarchical",
                "horizon": "tactical",
                "error": "no_active_goal",
                "goal": None,
                "plan_id": None,
                "steps": [],
                "timestamp": _now_utc().isoformat(),
            }

        plan = self.tactical.create_plan(context, current_goal)
        with self._lock:
            self.active_plan = plan
        return {
            "layer": "tactical",
            "engine": "hierarchical",
            "horizon": "tactical",
            "goal": current_goal.description,
            "goal_id": current_goal.goal_id,
            "plan_id": plan.plan_id,
            "steps": list(plan.steps),
            "duration_seconds": plan.estimated_duration.total_seconds(),
            "duration": str(plan.estimated_duration),
            "cost": plan.estimated_cost,
            "expected_reward": plan.estimated_reward,
            "timestamp": _now_utc().isoformat(),
        }

    # -- operational ---------------------------------------------------

    def _operational_decision(self, context: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            plan = self.active_plan
            goal = self.active_goal

        available_actions: list[str] | None = None
        if plan is not None and not plan.is_complete():
            next_step = plan.next_action()
            if isinstance(next_step, dict):
                action = next_step.get("action")
                if isinstance(action, str) and action:
                    available_actions = [action]

        decision_context = DecisionContext(
            intent=str(context.get("intent") or "general_decision"),
            domain=str(context.get("domain") or (goal.domain if goal else "business")),
            user_id=context.get("user_id"),
            organization_id=context.get("organization_id"),
            risk_tolerance=float(context.get("risk_tolerance", 0.5)),
            time_horizon="immediate",
            constraints=dict(context.get("constraints") or {}),
            metadata=dict(context),
        )

        try:
            output = self.operational.decide(decision_context, available_actions=available_actions)
        except Exception as exc:
            logger.warning("hierarchical.operational.decide failed: %s", exc, exc_info=True)
            return {
                "layer": "operational",
                "engine": "hierarchical",
                "horizon": "immediate",
                "error": "operational_failure",
                "error_message": str(exc),
                "timestamp": _now_utc().isoformat(),
            }

        plan_advanced = False
        with self._lock:
            current_plan = self.active_plan
            if (
                current_plan is plan
                and current_plan is not None
                and not current_plan.is_complete()
            ):
                next_step = current_plan.next_action()
                if isinstance(next_step, dict) and next_step.get("action") == output.action:
                    current_plan.current_step += 1
                    plan_advanced = True

        steps_total = len(plan.steps) if plan is not None else 0
        steps_done = plan.current_step if plan is not None else 0
        return {
            "layer": "operational",
            "engine": "hierarchical",
            "horizon": "immediate",
            "action": output.action,
            "action_type": output.action_type,
            "confidence": output.confidence,
            "expected_reward": output.expected_reward,
            "exploration_bonus": output.exploration_bonus,
            "reasoning": list(output.reasoning),
            "active_plan": plan.plan_id if plan is not None else None,
            "active_goal": goal.description if goal is not None else None,
            "plan_progress": f"{steps_done}/{steps_total}" if plan is not None else None,
            "plan_advanced": plan_advanced,
            "intent": decision_context.intent,
            "domain": decision_context.domain,
            "user_id": decision_context.user_id,
            "organization_id": decision_context.organization_id,
            "risk_tolerance": decision_context.risk_tolerance,
            "time_horizon": decision_context.time_horizon,
            "constraints": dict(decision_context.constraints),
            "metadata": dict(decision_context.metadata),
            "context": dict(context),
            "learning_log_id": output.learning_log_id,
            "timestamp": output.timestamp.isoformat(),
        }

    # -- internals -----------------------------------------------------

    def _load_goals(self, context: dict[str, Any]) -> list[StrategicGoal]:
        try:
            goals = self._goals_provider(context)
        except Exception as exc:
            logger.warning("hierarchical.goals_provider raised: %s", exc, exc_info=True)
            return []
        return [g for g in goals if isinstance(g, StrategicGoal)]


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------


_singleton: HierarchicalPolicy | None = None
_singleton_lock = threading.Lock()


def get_hierarchical_policy() -> HierarchicalPolicy:
    """Return the process-wide ``HierarchicalPolicy`` singleton."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = HierarchicalPolicy()
    return _singleton


def reset_hierarchical_policy() -> None:
    """Test-only: drop the singleton so the next ``get_hierarchical_policy()``
    rebuilds it (e.g. with new env vars or a swapped operational engine)."""
    global _singleton
    with _singleton_lock:
        _singleton = None


__all__ = [
    "GoalsProvider",
    "HierarchicalPolicy",
    "MCTSNode",
    "StrategicGoal",
    "StrategicPlanner",
    "TacticalPlan",
    "TacticalPlanner",
    "default_goals_provider",
    "get_hierarchical_policy",
    "reset_hierarchical_policy",
]
