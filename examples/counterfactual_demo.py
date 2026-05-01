"""Demo: counterfactual analysis + causal explanation, end-to-end.

Run from the repo root::

    python examples/counterfactual_demo.py

The script never opens a real DB - it builds an in-memory ``LearningLog``
substitute, injects a tiny scripted world model, and walks both the
counterfactual engine and the causal explainer over the result. A second
section shows the ``explain=True`` flag attached to a live router decision.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from services.causal_explainer import (  # noqa: E402
    CausalExplainer,
    CausalGraphBuilder,
)
from services.counterfactual_engine import (  # noqa: E402
    CounterfactualEngine,
    OutcomeSimulator,
)
from services.decision_router import DecisionRouter  # noqa: E402
from services.policy_engine import PolicyEngine  # noqa: E402


# ---------------------------------------------------------------------------
# In-memory mocks (no database required)
# ---------------------------------------------------------------------------


@dataclass
class _Log:
    id: int
    action_type: str
    outcome_json: dict[str, Any]
    success: bool = False
    user_id: int = 1
    organization_id: int = 1
    context: Any = None


class _Query:
    def __init__(self, rows: list[_Log]) -> None:
        self._rows = list(rows)

    def filter(self, *_a: Any, **_kw: Any) -> "_Query":
        return self

    def order_by(self, *_a: Any) -> "_Query":
        return self

    def limit(self, n: int) -> "_Query":
        self._rows = self._rows[:n]
        return self

    def all(self) -> list[_Log]:
        return list(self._rows)


class _ScalarResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


def _extract_int_id(stmt: Any) -> int | None:
    """Pull a literal int out of ``where(col == int)`` for either SQLAlchemy
    BinaryExpression layout."""
    where = getattr(stmt, "whereclause", None)
    if where is None:
        return None
    right = getattr(where, "right", None)
    value = getattr(right, "value", None) if right is not None else None
    if isinstance(value, int):
        return value
    try:
        for child in where.get_children():
            cv = getattr(child, "value", None)
            if isinstance(cv, int):
                return cv
    except Exception:
        pass
    return None


class _Session:
    def __init__(self, rows_by_id: dict[int, _Log], history: list[_Log]) -> None:
        self.rows_by_id = rows_by_id
        self.history = history

    def query(self, *_a: Any, **_kw: Any) -> _Query:
        return _Query(self.history)

    def execute(self, stmt: Any) -> _ScalarResult:
        target = _extract_int_id(stmt)
        if target is None:
            return _ScalarResult(None)
        return _ScalarResult(self.rows_by_id.get(target))

    def close(self) -> None:
        pass

    def __enter__(self) -> "_Session":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


class _ScriptedWorldModel:
    """Returns a different prediction depending on the action."""

    def predict_outcome(self, outcome: str, *, conditions: dict[str, Any] | None = None) -> dict[str, Any]:
        action = (conditions or {}).get("action", "")
        scripts = {
            "buy": {"p": 0.85, "evidence_n": 30},
            "sell": {"p": 0.20, "evidence_n": 30},
            "hold": {"p": 0.55, "evidence_n": 30},
            "hedge": {"p": 0.65, "evidence_n": 30},
        }
        return {**scripts.get(action, {"p": 0.5, "evidence_n": 5}), "outcome": outcome}


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


def _print_section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def _show_analysis(analysis: Any) -> None:
    print(f"actual action  : {analysis.actual_action}")
    print(f"actual reward  : {analysis.actual_reward:+.3f}")
    print(f"alternatives   : {len(analysis.alternatives)}")
    for s in sorted(analysis.alternatives, key=lambda x: x.expected_reward, reverse=True):
        print(f"  - {s.action:10s} reward={s.expected_reward:+.3f} confidence={s.confidence:.2f}")
        print(f"      {s.reasoning}")
    if analysis.best_alternative is not None:
        print(f"best alt       : {analysis.best_alternative.action} ({analysis.best_alternative.expected_reward:+.3f})")
    print(f"regret         : {analysis.regret:+.3f}")
    print(f"lesson         : {analysis.lesson}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s :: %(message)s")

    # Fake decision history.
    historical = [_Log(id=10 + i, action_type="hold", outcome_json={"reward": 0.05},
                       success=True, context={"domain": "trading"}) for i in range(3)]
    target_log = _Log(
        id=1, action_type="hold", outcome_json={"reward": 0.10}, success=True,
        context={"domain": "trading", "risk_tolerance": 0.4},
    )
    rows = {target_log.id: target_log, **{r.id: r for r in historical}}

    factory = lambda: _Session(rows_by_id=rows, history=historical)
    world = _ScriptedWorldModel()

    _print_section("1. Counterfactual analysis (decision_id=1, action='hold')")
    engine = CounterfactualEngine(
        simulator=OutcomeSimulator(world_model=world, session_factory=factory),
        session_factory=factory,
    )
    analysis = engine.analyze(decision_id=1)
    _show_analysis(analysis)

    _print_section("2. Causal explanation for that same decision")
    explainer = CausalExplainer()
    decision_dict = {
        "action": target_log.action_type,
        "confidence": 0.62,
        "features": [1.0, 0.4, 0.7, 0.2, 0.3, 0.5, 0.1, 0.0, 0.0, 0.0],
        "context": {"domain": "trading", "risk_tolerance": 0.4},
        "world_state": {"prediction": {"confidence": 0.8}},
    }
    explanation = explainer.explain(decision_dict, decision_id=target_log.id)
    print(f"action         : {explanation.action}")
    print(f"text           : {explanation.text_explanation}")
    print("top features   :")
    for fi in explanation.feature_importance[:5]:
        print(f"  - {fi.feature_name:18s} importance={fi.importance:.2%} contribution={fi.contribution:+.2f}")
    print("counterfactuals:")
    for c in explanation.counterfactuals:
        print(f"  - {c}")
    print("causal graph   :")
    print(json.dumps(CausalGraphBuilder.to_dict(explanation.causal_graph), indent=2, default=str))

    _print_section("3. Live router with explain=True")
    router = DecisionRouter(policy_engine=PolicyEngine(n_features=20, alpha=1.0))
    decision, engine_used = router.route(
        {"intent": "demo", "domain": "trading", "explain": True, "risk_tolerance": 0.4},
        available_actions=["buy", "sell", "hold"],
        user_id=1,
    )
    print(f"engine used    : {engine_used}")
    print(f"action         : {decision.get('action')}")
    print(f"explanation    : {decision.get('explanation', {}).get('text', '<none>')}")
    if "explanation" in decision:
        print("top features   :")
        for fi in decision["explanation"]["top_features"]:
            print(f"  - {fi['name']:18s} importance={fi['importance']:.2%}")


if __name__ == "__main__":
    main()
