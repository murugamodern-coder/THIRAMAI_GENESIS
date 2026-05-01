"""Tests for :mod:`services.counterfactual_engine` and
:mod:`services.causal_explainer`.

Design notes
------------

* No real database is touched. ``OutcomeSimulator`` and
  ``CounterfactualEngine`` accept an injected session factory and the
  factory is wired to a small in-memory fake here.
* ``BayesianWorldModel`` is replaced by a ``_FakeWorldModel`` that returns
  scripted ``predict_outcome`` payloads, so the world-model integration is
  exercised without hydrating any DB snapshot.
* ``DecisionRouter`` explain-hook tests don't need a real ``PolicyEngine``
  state - they hit the explainer with a stub decision that mimics what
  the engine actually returns (``action`` / ``confidence`` /
  ``features`` / ``world_state``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pytest

from services.causal_explainer import (
    CausalExplainer,
    CausalExplanation,
    CausalGraphBuilder,
    FeatureImportance,
    GRAPH_AVAILABLE,
    MagnitudeAttributor,
    NaturalLanguageGenerator,
    _features_from_context,
    _stable_unit,
    get_causal_explainer,
    reset_causal_explainer,
)
from services.counterfactual_engine import (
    CounterfactualAnalysis,
    CounterfactualEngine,
    CounterfactualScenario,
    OutcomeSimulator,
    _domain_from_context,
    _stable_seed,
    get_counterfactual_engine,
    reset_counterfactual_engine,
)
from services.decision_router import DecisionRouter, reset_decision_router
from services.policy_engine import PolicyEngine, reset_policy_engine


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeWorldModel:
    """Returns a scripted ``predict_outcome`` payload."""

    def __init__(self, payload: dict[str, Any] | None = None, *, raise_exc: bool = False) -> None:
        self.payload = payload or {"p": 0.7, "evidence_n": 30, "outcome": "growth_unlocked"}
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self.raise_exc = raise_exc

    def predict_outcome(self, outcome: str, *, conditions: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((outcome, dict(conditions or {})))
        if self.raise_exc:
            raise RuntimeError("simulated world model failure")
        return dict(self.payload)


@dataclass
class _FakeLog:
    """In-memory mimic of :class:`core.db.models.LearningLog`."""

    id: int
    action_type: str
    outcome_json: dict[str, Any]
    success: bool | None = True
    user_id: int | None = 1
    organization_id: int = 1
    context: Any = None  # dict, json string, or None
    created_at: Any = None


def _extract_int_id(stmt: Any) -> int | None:
    """Pull the int literal out of a ``where(col == int)`` SQL clause.

    Robust to both SQLAlchemy's BinaryExpression layout (``stmt.whereclause.right.value``)
    and the older ``get_children`` walking pattern."""
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


class _FakeQuery:
    def __init__(self, rows: list[_FakeLog]) -> None:
        self._rows = list(rows)

    def filter(self, *_: Any, **__: Any) -> "_FakeQuery":
        return self

    def order_by(self, *_: Any) -> "_FakeQuery":
        return self

    def limit(self, n: int) -> "_FakeQuery":
        self._rows = self._rows[:n]
        return self

    def all(self) -> list[_FakeLog]:
        return list(self._rows)


class _FakeScalarResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _FakeSession:
    """Drop-in for a SQLAlchemy ``Session`` good enough for the engine code."""

    def __init__(self, rows_by_id: dict[int, _FakeLog] | None = None,
                 history: list[_FakeLog] | None = None) -> None:
        self.rows_by_id = rows_by_id or {}
        self.history = history or []
        self.closed = False

    def query(self, *_: Any, **__: Any) -> _FakeQuery:
        return _FakeQuery(self.history)

    def execute(self, stmt: Any) -> _FakeScalarResult:
        target_id = _extract_int_id(stmt)
        if target_id is None:
            # No id parsed -> behave like an unknown id rather than picking
            # the first row arbitrarily.
            return _FakeScalarResult(None)
        return _FakeScalarResult(self.rows_by_id.get(target_id))

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


def _factory(session: _FakeSession) -> Any:
    return lambda: session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_all():
    reset_policy_engine()
    reset_decision_router()
    reset_counterfactual_engine()
    reset_causal_explainer()
    yield
    reset_policy_engine()
    reset_decision_router()
    reset_counterfactual_engine()
    reset_causal_explainer()


@pytest.fixture()
def fake_world() -> _FakeWorldModel:
    return _FakeWorldModel()


@pytest.fixture()
def empty_session() -> _FakeSession:
    return _FakeSession()


@pytest.fixture()
def simulator(fake_world: _FakeWorldModel, empty_session: _FakeSession) -> OutcomeSimulator:
    return OutcomeSimulator(world_model=fake_world, session_factory=_factory(empty_session))


# ===========================================================================
# Helpers: stable seed + domain extraction
# ===========================================================================


def test_stable_seed_is_deterministic_across_calls():
    assert _stable_seed("a", "b", 1) == _stable_seed("a", "b", 1)


def test_stable_seed_handles_none_components():
    # Must not raise when components are None.
    seed = _stable_seed(None, "x", None)
    assert isinstance(seed, int)


def test_stable_seed_independent_of_pythonhashseed(monkeypatch):
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    a = _stable_seed("trade", "buy", 42)
    monkeypatch.setenv("PYTHONHASHSEED", "999999")
    b = _stable_seed("trade", "buy", 42)
    assert a == b


def test_domain_from_context_returns_default_when_missing():
    assert _domain_from_context(None) == "business"
    assert _domain_from_context({}) == "business"


def test_domain_from_context_normalises_case_and_whitespace():
    assert _domain_from_context({"domain": "  TRADING  "}) == "trading"


def test_domain_from_context_falls_back_when_value_invalid():
    assert _domain_from_context({"domain": ""}, default="personal") == "personal"
    assert _domain_from_context({"domain": 42}, default="trading") == "trading"


# ===========================================================================
# Dataclasses
# ===========================================================================


def test_counterfactual_scenario_as_dict_round_trip():
    s = CounterfactualScenario(
        action="buy", simulated_outcome={"reward": 0.6}, expected_reward=0.6,
        confidence=0.7, reasoning="ok",
    )
    d = s.as_dict()
    assert d["action"] == "buy"
    assert d["expected_reward"] == 0.6


def test_counterfactual_analysis_as_dict_includes_alternatives():
    s = CounterfactualScenario("buy", {"reward": 0.6}, 0.6, 0.7, "ok")
    a = CounterfactualAnalysis(
        decision_id=1, actual_action="hold", actual_outcome={}, actual_reward=0.0,
        alternatives=[s], best_alternative=s, regret=0.6, lesson="lesson",
    )
    d = a.as_dict()
    assert len(d["alternatives"]) == 1
    assert d["best_alternative"]["action"] == "buy"
    assert d["regret"] == pytest.approx(0.6)


# ===========================================================================
# OutcomeSimulator - world model path
# ===========================================================================


def test_simulator_uses_world_model_p_key(fake_world, empty_session):
    fake_world.payload = {"p": 0.8, "evidence_n": 60}
    sim = OutcomeSimulator(world_model=fake_world, session_factory=_factory(empty_session))
    outcome, reward = sim.simulate({"domain": "business"}, "invest", "business",
                                   decision_id=1)
    # reward = 2 * 0.8 - 1 = 0.6 (plus tiny noise scaled by 1 - confidence)
    assert outcome["world_model_prediction"]["probability"] == 0.8
    assert outcome["world_model_prediction"]["reward"] == pytest.approx(0.6)
    assert outcome["historical_match"] is False


def test_simulator_handles_world_model_exception(empty_session):
    sim = OutcomeSimulator(
        world_model=_FakeWorldModel(raise_exc=True),
        session_factory=_factory(empty_session),
    )
    outcome, _ = sim.simulate({}, "buy", "trading", decision_id=2)
    # Falls back to neutral prediction.
    assert outcome["world_model_prediction"]["confidence"] == 0.3
    assert outcome["world_model_prediction"]["reward"] == 0.0


def test_simulator_confidence_grows_with_evidence(empty_session):
    low_evidence = _FakeWorldModel(payload={"p": 0.5, "evidence_n": 0})
    high_evidence = _FakeWorldModel(payload={"p": 0.5, "evidence_n": 30})
    sim_low = OutcomeSimulator(world_model=low_evidence, session_factory=_factory(empty_session))
    sim_high = OutcomeSimulator(world_model=high_evidence, session_factory=_factory(empty_session))
    out_low, _ = sim_low.simulate({}, "buy", "trading", decision_id=3)
    out_high, _ = sim_high.simulate({}, "buy", "trading", decision_id=3)
    assert out_low["confidence"] < out_high["confidence"]


def test_simulator_passes_action_and_domain_to_world_model(simulator, fake_world):
    simulator.simulate({"domain": "trading"}, "hedge", "trading", decision_id=4)
    assert len(fake_world.calls) == 1
    outcome_name, conditions = fake_world.calls[0]
    assert conditions["action"] == "hedge"
    assert conditions["domain"] == "trading"


def test_simulator_drops_non_primitive_context_values(simulator, fake_world):
    simulator.simulate(
        {"domain": "business", "complex": {"nested": "dict"}, "n": 5, "ok": True, "name": "x"},
        "invest", "business", decision_id=5,
    )
    _, conditions = fake_world.calls[0]
    assert "complex" not in conditions
    assert conditions["n"] == 5
    assert conditions["ok"] is True


# ===========================================================================
# OutcomeSimulator - historical lookup
# ===========================================================================


def _historical_session(rows: list[_FakeLog]) -> _FakeSession:
    return _FakeSession(history=rows)


def test_simulator_historical_lookup_blends_with_world_model(fake_world):
    rows = [_FakeLog(
        id=i, action_type="invest", outcome_json={"reward": 0.9},
        success=True, context={"domain": "business"},
    ) for i in range(5)]
    sim = OutcomeSimulator(
        world_model=fake_world,
        session_factory=_factory(_historical_session(rows)),
    )
    fake_world.payload = {"p": 0.5, "evidence_n": 30}
    outcome, reward = sim.simulate({}, "invest", "business", decision_id=10)
    # Expected: 0.7 * 0.9 + 0.3 * 0.0 = 0.63 (plus tiny noise)
    assert outcome["historical_match"] is True
    assert outcome["historical_reward"] == pytest.approx(0.9)
    assert reward > 0.55


def test_simulator_historical_lookup_filters_by_domain(fake_world):
    rows = [
        _FakeLog(id=1, action_type="invest", outcome_json={"reward": 0.9},
                 context={"domain": "trading"}),  # wrong domain
        _FakeLog(id=2, action_type="invest", outcome_json={"reward": -0.4},
                 context={"domain": "business"}),
    ]
    sim = OutcomeSimulator(
        world_model=fake_world,
        session_factory=_factory(_historical_session(rows)),
    )
    outcome, _ = sim.simulate({}, "invest", "business", decision_id=11)
    assert outcome["historical_reward"] == pytest.approx(-0.4)


def test_simulator_historical_lookup_returns_none_without_factory(fake_world):
    sim = OutcomeSimulator(world_model=fake_world, session_factory=None)
    outcome, _ = sim.simulate({}, "invest", "business", decision_id=12)
    assert outcome["historical_match"] is False


def test_simulator_historical_lookup_handles_session_failure(fake_world):
    def bad_factory():
        raise RuntimeError("db down")
    sim = OutcomeSimulator(world_model=fake_world, session_factory=bad_factory)
    outcome, _ = sim.simulate({}, "invest", "business", decision_id=13)
    assert outcome["historical_match"] is False


# ===========================================================================
# OutcomeSimulator - noise + reproducibility
# ===========================================================================


def test_simulator_does_not_mutate_global_numpy_state(simulator):
    np.random.seed(42)
    expected = np.random.standard_normal(3)
    np.random.seed(42)
    simulator.simulate({}, "invest", "business", decision_id=99)
    actual = np.random.standard_normal(3)
    np.testing.assert_array_equal(expected, actual)


def test_simulator_is_reproducible_for_same_decision(simulator):
    out1, r1 = simulator.simulate({}, "invest", "business", decision_id=7)
    out2, r2 = simulator.simulate({}, "invest", "business", decision_id=7)
    assert r1 == r2
    assert out1["noise"] == out2["noise"]


def test_simulator_noise_differs_for_different_decisions(empty_session):
    """The noise term is scaled by ``1 - confidence`` so we deliberately use a
    low-evidence world model here - the default fixture's evidence_n=30 saturates
    confidence to 1.0 and zeros the noise."""
    sim = OutcomeSimulator(
        world_model=_FakeWorldModel(payload={"p": 0.5, "evidence_n": 1}),
        session_factory=_factory(empty_session),
    )
    _, r1 = sim.simulate({}, "invest", "business", decision_id=7)
    _, r2 = sim.simulate({}, "invest", "business", decision_id=8)
    assert r1 != r2  # different seed -> different noise


# ===========================================================================
# CounterfactualEngine
# ===========================================================================


def _engine_with_log(log: _FakeLog, world: _FakeWorldModel | None = None,
                     history: list[_FakeLog] | None = None) -> CounterfactualEngine:
    session = _FakeSession(rows_by_id={log.id: log}, history=history or [])
    sim = OutcomeSimulator(world_model=world or _FakeWorldModel(),
                           session_factory=_factory(session))
    return CounterfactualEngine(simulator=sim, session_factory=_factory(session))


def test_engine_raises_for_missing_decision():
    factory = lambda: _FakeSession(rows_by_id={})
    eng = CounterfactualEngine(
        simulator=OutcomeSimulator(world_model=_FakeWorldModel(),
                                    session_factory=factory),
        session_factory=factory,
    )
    with pytest.raises(ValueError):
        eng.analyze(decision_id=999)


def test_engine_analyse_drops_actual_action_from_alternatives():
    log = _FakeLog(id=1, action_type="hold", outcome_json={"reward": 0.0},
                   context={"domain": "trading"})
    eng = _engine_with_log(log)
    analysis = eng.analyze(decision_id=1)
    assert "hold" not in [s.action for s in analysis.alternatives]


def test_engine_uses_explicit_alternatives_when_provided():
    log = _FakeLog(id=1, action_type="hold", outcome_json={"reward": 0.0},
                   context={"domain": "trading"})
    eng = _engine_with_log(log)
    analysis = eng.analyze(decision_id=1, alternative_actions=["sell", "hold"])
    actions = [s.action for s in analysis.alternatives]
    assert actions == ["sell"]  # hold was the actual action, dropped


def test_engine_infers_alternatives_per_domain():
    log = _FakeLog(id=1, action_type="market_research", outcome_json={"reward": 0.0},
                   context={"domain": "business"})
    eng = _engine_with_log(log)
    analysis = eng.analyze(decision_id=1)
    actions = {s.action for s in analysis.alternatives}
    assert {"invest", "save", "expand", "optimize"} == actions


def test_engine_picks_best_alternative_by_expected_reward():
    log = _FakeLog(id=1, action_type="hold", outcome_json={"reward": 0.0},
                   context={"domain": "trading"})
    eng = _engine_with_log(log, world=_FakeWorldModel(payload={"p": 0.9, "evidence_n": 30}))
    analysis = eng.analyze(decision_id=1)
    assert analysis.best_alternative is not None
    assert analysis.best_alternative.expected_reward == max(
        s.expected_reward for s in analysis.alternatives
    )


def test_engine_regret_is_positive_when_best_alternative_beats_actual():
    log = _FakeLog(id=1, action_type="hold", outcome_json={"reward": 0.0},
                   context={"domain": "trading"})
    eng = _engine_with_log(log, world=_FakeWorldModel(payload={"p": 0.9, "evidence_n": 30}))
    analysis = eng.analyze(decision_id=1)
    assert analysis.regret > 0


def test_engine_regret_is_zero_when_no_alternatives():
    """If we don't supply any alternatives and the actual action exhausts the
    inferred set, the engine should still produce a usable analysis."""
    log = _FakeLog(id=1, action_type="hold", outcome_json={"reward": 0.5},
                   context={"domain": "trading"})
    eng = _engine_with_log(log)
    analysis = eng.analyze(decision_id=1, alternative_actions=["hold"])  # only the actual
    assert analysis.alternatives == []
    assert analysis.best_alternative is None
    assert analysis.regret == 0.0


def test_engine_extracts_reward_from_outcome_json():
    log = _FakeLog(id=1, action_type="hold", outcome_json={"reward": 0.42},
                   context={"domain": "trading"})
    eng = _engine_with_log(log)
    analysis = eng.analyze(decision_id=1)
    assert analysis.actual_reward == pytest.approx(0.42)


def test_engine_extracts_reward_from_success_when_outcome_missing():
    log = _FakeLog(id=1, action_type="hold", outcome_json={}, success=True,
                   context={"domain": "trading"})
    eng = _engine_with_log(log)
    analysis = eng.analyze(decision_id=1)
    assert analysis.actual_reward == 1.0


def test_engine_extracts_reward_from_failure():
    log = _FakeLog(id=1, action_type="hold", outcome_json={}, success=False,
                   context={"domain": "trading"})
    eng = _engine_with_log(log)
    analysis = eng.analyze(decision_id=1)
    assert analysis.actual_reward == -0.5


def test_engine_handles_string_context_json():
    import json as _json
    log = _FakeLog(id=1, action_type="hold", outcome_json={"reward": 0.0},
                   context=_json.dumps({"domain": "personal"}))
    eng = _engine_with_log(log)
    analysis = eng.analyze(decision_id=1)
    actions = {s.action for s in analysis.alternatives}
    assert {"focus", "delegate", "defer", "decline"} == actions


def test_engine_lesson_for_no_regret_says_good_decision():
    # World model very negative on alternatives, actual_reward positive -> regret <= 0.
    log = _FakeLog(id=1, action_type="hold", outcome_json={"reward": 0.9},
                   context={"domain": "trading"})
    eng = _engine_with_log(log, world=_FakeWorldModel(payload={"p": 0.1, "evidence_n": 30}))
    analysis = eng.analyze(decision_id=1)
    assert "good decision" in analysis.lesson.lower()


def test_engine_lesson_for_significant_regret():
    # Force very high best-alt reward and very low actual reward.
    log = _FakeLog(id=1, action_type="hold", outcome_json={"reward": -0.9},
                   context={"domain": "trading"})
    eng = _engine_with_log(log, world=_FakeWorldModel(payload={"p": 0.95, "evidence_n": 30}))
    analysis = eng.analyze(decision_id=1)
    assert "significant regret" in analysis.lesson.lower()


# ===========================================================================
# CausalGraphBuilder
# ===========================================================================


def test_graph_builder_creates_expected_nodes():
    builder = CausalGraphBuilder()
    g = builder.build({}, {}, np.zeros(20), "buy", 0.7)
    expected = {"Context", "WorldState", "Features", "BanditWeights", "Action"}
    assert expected <= set(g.nodes)


def test_graph_builder_action_node_value_is_passed_through():
    g = CausalGraphBuilder().build({}, {}, np.zeros(5), "hedge", 0.5)
    assert g.nodes["Action"]["value"] == "hedge"


def test_graph_builder_to_dict_produces_serialisable_payload():
    g = CausalGraphBuilder().build({}, {}, np.zeros(5), "buy", 0.7)
    payload = CausalGraphBuilder.to_dict(g)
    assert "nodes" in payload and "edges" in payload
    assert any(n["id"] == "Action" for n in payload["nodes"])
    # Payload must be JSON serialisable.
    import json as _json
    _json.dumps(payload, default=str)


def test_graph_builder_edge_count_matches_spec():
    g = CausalGraphBuilder().build({}, {}, np.zeros(5), "buy", 0.7)
    payload = CausalGraphBuilder.to_dict(g)
    edge_pairs = {(e["source"], e["target"]) for e in payload["edges"]}
    expected = {
        ("Context", "Features"),
        ("WorldState", "Features"),
        ("Features", "BanditWeights"),
        ("BanditWeights", "Action"),
    }
    assert edge_pairs == expected


@pytest.mark.skipif(not GRAPH_AVAILABLE, reason="networkx not installed")
def test_graph_builder_uses_networkx_when_available():
    import networkx as nx
    g = CausalGraphBuilder().build({}, {}, np.zeros(5), "buy", 0.5)
    assert isinstance(g, nx.DiGraph)


def test_graph_builder_works_without_networkx():
    """The fallback DiGraph also produces a serialisable payload."""
    g = CausalGraphBuilder().build({}, {}, np.zeros(5), "buy", 0.5)
    payload = CausalGraphBuilder.to_dict(g)
    assert len(payload["nodes"]) == 5
    assert len(payload["edges"]) == 4


# ===========================================================================
# MagnitudeAttributor
# ===========================================================================


def test_attributor_normalises_importance_to_sum_one():
    attr = MagnitudeAttributor()
    out = attr.attribute(np.asarray([1.0, 2.0, 3.0]), ["a", "b", "c"])
    assert sum(f.importance for f in out) == pytest.approx(1.0)


def test_attributor_sorts_by_importance_desc():
    attr = MagnitudeAttributor()
    out = attr.attribute(np.asarray([1.0, 5.0, 3.0]), ["a", "b", "c"])
    assert out[0].feature_name == "b"
    assert [f.feature_name for f in out] == ["b", "c", "a"]


def test_attributor_handles_zero_features_without_division():
    attr = MagnitudeAttributor()
    out = attr.attribute(np.zeros(3), ["x", "y", "z"])
    assert all(f.importance == pytest.approx(1.0 / 3.0) for f in out)


def test_attributor_handles_empty_features():
    assert MagnitudeAttributor().attribute(np.asarray([]), []) == []


def test_attributor_pads_feature_names_when_too_few_provided():
    attr = MagnitudeAttributor()
    out = attr.attribute(np.asarray([1.0, 2.0, 3.0]), ["only_one"])
    names = sorted(f.feature_name for f in out)
    # 1 supplied + 2 generated
    assert "only_one" in names
    assert any(n.startswith("feature_") for n in names)


def test_attributor_records_signed_contribution():
    attr = MagnitudeAttributor()
    out = attr.attribute(np.asarray([-3.0, 1.0]), ["a", "b"])
    contrib = {f.feature_name: f.contribution for f in out}
    assert contrib["a"] == -3.0
    assert contrib["b"] == 1.0


# ===========================================================================
# NaturalLanguageGenerator
# ===========================================================================


def test_nlg_includes_action_and_confidence_percentage():
    nlg = NaturalLanguageGenerator()
    text = nlg.generate("buy", 0.83, [], {}, {"domain": "trading"})
    assert "'buy'" in text
    assert "83%" in text


def test_nlg_lists_top_three_factors_only():
    nlg = NaturalLanguageGenerator()
    importance = [
        FeatureImportance(f"f{i}", importance=0.2, contribution=1.0, description="")
        for i in range(5)
    ]
    text = nlg.generate("buy", 0.5, importance, {}, {})
    assert "f0" in text and "f1" in text and "f2" in text
    assert "f3" not in text and "f4" not in text


def test_nlg_describes_risk_tolerance_buckets():
    nlg = NaturalLanguageGenerator()
    high = nlg.generate("x", 0.5, [], {}, {"risk_tolerance": 0.9})
    low = nlg.generate("x", 0.5, [], {}, {"risk_tolerance": 0.1})
    mid = nlg.generate("x", 0.5, [], {}, {"risk_tolerance": 0.5})
    assert "high risk" in high
    assert "low risk" in low
    assert "moderate risk" in mid


def test_nlg_mentions_world_model_when_high_confidence():
    nlg = NaturalLanguageGenerator()
    text = nlg.generate("x", 0.5, [], {"prediction": {"confidence": 0.9}}, {})
    assert "World model" in text


def test_nlg_omits_world_model_when_low_confidence():
    nlg = NaturalLanguageGenerator()
    text = nlg.generate("x", 0.5, [], {"prediction": {"confidence": 0.4}}, {})
    assert "World model" not in text


# ===========================================================================
# CausalExplainer pipeline
# ===========================================================================


def test_explainer_uses_decision_features_when_present():
    explainer = CausalExplainer()
    decision = {
        "action": "buy",
        "confidence": 0.8,
        "features": [1.0, 0.0, 0.5, 0.0, 0.2],
        "context": {"domain": "trading", "risk_tolerance": 0.6},
    }
    explanation = explainer.explain(decision)
    assert explanation.action == "buy"
    assert explanation.feature_importance  # non-empty
    # Top feature should be index 0 (highest |value|).
    assert explanation.feature_importance[0].contribution == 1.0


def test_explainer_falls_back_to_context_features():
    explainer = CausalExplainer()
    decision = {
        "action": "save",
        "confidence": 0.5,
        "context": {"domain": "business", "risk_tolerance": 0.4, "constraints": {"a": 1, "b": 2}},
    }
    explanation = explainer.explain(decision)
    # Bias feature is value 1.0 (highest magnitude in fallback).
    assert any(f.contribution == 1.0 for f in explanation.feature_importance)


def test_explainer_uses_metadata_features_when_top_level_absent():
    explainer = CausalExplainer()
    decision = {
        "action": "x", "confidence": 0.5,
        "metadata": {"features": [0.0, 5.0, 0.0], "feature_names": ["a", "b", "c"]},
    }
    explanation = explainer.explain(decision)
    assert explanation.feature_importance[0].feature_name == "b"


def test_explainer_returns_natural_language_explanation():
    explanation = CausalExplainer().explain(
        {"action": "hedge", "confidence": 0.7, "features": [1.0] * 5,
         "context": {"domain": "trading", "risk_tolerance": 0.5}}
    )
    assert isinstance(explanation.text_explanation, str)
    assert "hedge" in explanation.text_explanation


def test_explainer_handles_missing_action_with_unknown_default():
    explanation = CausalExplainer().explain({})
    assert explanation.action == "unknown"


def test_explainer_attaches_decision_id_when_provided():
    explanation = CausalExplainer().explain({"action": "x"}, decision_id=42)
    assert explanation.decision_id == 42


def test_explainer_counterfactuals_top_two_only():
    explanation = CausalExplainer().explain(
        {"action": "buy", "features": [1.0, 0.9, 0.8, 0.7]}
    )
    assert len(explanation.counterfactuals) <= 2


def test_explanation_as_dict_serialises_graph():
    explanation = CausalExplainer().explain(
        {"action": "buy", "features": [1.0, 0.0, 0.0]}
    )
    payload = explanation.as_dict(graph_to_dict=CausalGraphBuilder.to_dict)
    assert "causal_graph" in payload
    assert payload["action"] == "buy"


# ===========================================================================
# Helpers internal to causal_explainer
# ===========================================================================


def test_stable_unit_in_zero_to_one():
    for value in ("trading", "business", None, "", "0", "x" * 100):
        u = _stable_unit(value)
        assert 0.0 <= u < 1.0


def test_features_from_context_returns_20_dim():
    arr = _features_from_context({"domain": "trading", "risk_tolerance": 0.7})
    assert arr.shape == (20,)
    assert arr[0] == 1.0  # bias


def test_features_from_context_caps_constraint_count_at_one():
    arr = _features_from_context({"constraints": {f"c{i}": i for i in range(50)}})
    assert arr[4] == 1.0  # capped at 10/10


# ===========================================================================
# Singletons
# ===========================================================================


def test_counterfactual_engine_singleton_returns_same_instance():
    a = get_counterfactual_engine()
    b = get_counterfactual_engine()
    assert a is b


def test_counterfactual_engine_singleton_resets():
    a = get_counterfactual_engine()
    reset_counterfactual_engine()
    b = get_counterfactual_engine()
    assert a is not b


def test_causal_explainer_singleton_returns_same_instance():
    a = get_causal_explainer()
    b = get_causal_explainer()
    assert a is b


def test_causal_explainer_singleton_resets():
    a = get_causal_explainer()
    reset_causal_explainer()
    b = get_causal_explainer()
    assert a is not b


# ===========================================================================
# DecisionRouter explain wiring
# ===========================================================================


@pytest.fixture()
def fresh_router() -> DecisionRouter:
    return DecisionRouter(policy_engine=PolicyEngine(n_features=20, alpha=1.0))


def test_router_does_not_attach_explanation_by_default(fresh_router: DecisionRouter):
    decision, _ = fresh_router.route(
        {"intent": "test", "domain": "business"},
        available_actions=["a", "b"],
        user_id=1,
    )
    assert "explanation" not in decision


def test_router_attaches_explanation_when_flag_set(fresh_router: DecisionRouter):
    decision, _ = fresh_router.route(
        {"intent": "test", "domain": "business", "explain": True},
        available_actions=["a", "b"],
        user_id=1,
    )
    assert "explanation" in decision
    expl = decision["explanation"]
    assert {"text", "top_features", "causal_graph", "counterfactuals"} <= set(expl.keys())


def test_router_explanation_top_features_capped_at_five(fresh_router: DecisionRouter):
    decision, _ = fresh_router.route(
        {"intent": "test", "domain": "business", "explain": True},
        available_actions=["a", "b"],
        user_id=1,
    )
    assert len(decision["explanation"]["top_features"]) <= 5


def test_router_explanation_failure_does_not_crash(monkeypatch, fresh_router: DecisionRouter):
    # Force the explainer to raise; the request should still succeed.
    class _Boom:
        def explain(self, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "services.causal_explainer.get_causal_explainer", lambda: _Boom()
    )
    decision, _ = fresh_router.route(
        {"intent": "test", "domain": "business", "explain": True},
        available_actions=["a", "b"],
        user_id=1,
    )
    assert "explanation" not in decision  # silently dropped


def test_router_explanation_includes_serialisable_graph(fresh_router: DecisionRouter):
    import json as _json
    decision, _ = fresh_router.route(
        {"intent": "test", "domain": "business", "explain": True},
        available_actions=["a", "b"],
        user_id=1,
    )
    _json.dumps(decision["explanation"]["causal_graph"], default=str)  # must not raise
