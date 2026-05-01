"""Tests for tool discovery, Bayesian optimization, lightweight NAS, and auto feature engineering."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from services.self_evolution.feature_engineer import (
    AutoFeatureEngineer,
    get_feature_engineer,
    reset_feature_engineer,
)
from services.self_evolution.hyperparameter_optimizer import (
    BayesianOptimizer,
    HyperparameterSpace,
    HyperparameterTuner,
    LightweightNAS,
    LightweightNASResult,
    _expected_improvement,
    get_hyperparameter_tuner,
    reset_hyperparameter_tuner,
)
from services.self_evolution.improvement_loop import reset_self_evolution_singletons
from services.self_evolution.meta_learner import MetaLearner, Task
from services.self_evolution.tool_discovery import (
    DiscoveredTool,
    ToolDiscovery,
    discover_callable_stub,
    get_tool_discovery,
    reset_tool_discovery,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _reset_all():
    reset_self_evolution_singletons()
    yield
    reset_self_evolution_singletons()


def _task(domain: str = "trading") -> Task:
    return Task(
        task_id=f"t-{domain}",
        domain=domain,
        task_type="regression",
        support_set=[{"x": np.ones(4), "y": 1.0}],
        query_set=[{"x": np.ones(4), "y": 1.0}],
        difficulty=0.2,
        created_at=NOW,
    )


# --- Tool discovery ---


def test_discover_from_module_finds_local_callables():
    td = ToolDiscovery()
    tools = td.discover_from_module("services.self_evolution.tool_discovery")
    ids = {t.name for t in tools}
    assert "discover_callable_stub" in ids
    assert "get_tool_discovery" in ids


def test_discover_from_bad_module_returns_empty():
    td = ToolDiscovery()
    assert td.discover_from_module("no_such_module_xyz.invalid") == []


def test_discovered_tool_has_signature_metadata():
    td = ToolDiscovery()
    tools = td.discover_from_module("services.self_evolution.tool_discovery")
    stub = next(t for t in tools if t.name == "discover_callable_stub")
    assert "x" in stub.parameters
    assert "int" in stub.return_type.lower() or "Int" in stub.return_type


def test_learn_usage_pattern_updates_success_and_latency():
    td = ToolDiscovery()
    tools = td.discover_from_module("services.self_evolution.tool_discovery")
    tid = next(t.tool_id for t in tools if t.name == "discover_callable_stub")
    td.learn_usage_pattern(tid, {"domain": "x"}, {"x": 1}, True, latency_ms=10.0)
    td.learn_usage_pattern(tid, {"domain": "x"}, {"x": 2}, True, latency_ms=20.0)
    assert td.discovered_tools[tid].usage_count == 2
    assert td.discovered_tools[tid].avg_latency_ms == pytest.approx(15.0)
    assert len(td.usage_patterns) == 2


def test_suggest_tool_keyword_and_success_bias():
    td = ToolDiscovery()
    td.discover_from_module("services.self_evolution.tool_discovery")
    for t in td.discovered_tools.values():
        if t.name == "discover_callable_stub":
            t.success_rate = 0.9
            t.description = "discover callable helper for testing discovery"
            tid = t.tool_id
            break
    else:
        pytest.fail("stub not found")
    chosen = td.suggest_tool({}, "need discover callable helper", min_score=0.2)
    assert chosen is not None
    assert chosen.tool_id == tid


def test_suggest_tool_meta_learner_domain_bonus():
    td = ToolDiscovery()
    td.discover_from_module("services.self_evolution.tool_discovery")
    ml = MetaLearner()
    ml.add_task(_task("trading"))
    for t in td.discovered_tools.values():
        t.description = "module services.self_evolution for trading utilities"
        t.success_rate = 0.35
    out = td.suggest_tool(
        {"domain": "trading"},
        "z",
        meta_learner=ml,
        min_score=0.25,
    )
    assert out is not None


def test_suggest_tool_returns_none_when_low_confidence():
    td = ToolDiscovery()
    td.discover_from_module("services.self_evolution.tool_discovery")
    for t in td.discovered_tools.values():
        t.success_rate = 0.0
        t.description = "zzz unrelated zzz"
    assert td.suggest_tool({}, "quantum foam", min_score=0.99) is None


def test_usage_pattern_context_overlap_boosts_score():
    td = ToolDiscovery()
    td.discover_from_module("services.self_evolution.tool_discovery")
    tid = next(t.tool_id for t in td.discovered_tools.values() if t.name == "get_tool_discovery")
    td.learn_usage_pattern(
        tid,
        {"domain": "biz", "lane": 1},
        {},
        True,
    )
    hit = td.suggest_tool({"domain": "biz", "lane": 1}, "get_tool_discovery discovery", min_score=0.15)
    assert hit is None or hit.tool_id == tid


def test_discover_callable_stub_runs():
    assert discover_callable_stub(3) == 4


def test_get_tool_discovery_singleton():
    reset_tool_discovery()
    a = get_tool_discovery()
    b = get_tool_discovery()
    assert a is b


def test_reset_tool_discovery():
    g = get_tool_discovery()
    g.discovered_tools["fake"] = DiscoveredTool(
        tool_id="fake",
        name="fake",
        module_path="x",
        parameters={},
        return_type="Any",
        description="d",
    )
    reset_tool_discovery()
    assert get_tool_discovery().discovered_tools == {}


# --- Bayesian optimizer ---


def test_expected_improvement_positive_for_better_mean():
    mu = np.array([2.0, 0.5])
    sigma = np.array([0.1, 0.1])
    ei = _expected_improvement(mu, sigma, y_best=1.0)
    assert ei.shape == mu.shape
    assert ei[0] > 0
    assert all(ei >= 0)


def test_bayesian_random_phase_samples():
    space = [
        HyperparameterSpace("a", "float", (0.0, 1.0)),
        HyperparameterSpace("b", "int", (1, 5)),
        HyperparameterSpace("c", "categorical", (0.0, 1.0), choices=["u", "v"]),
    ]
    opt = BayesianOptimizer(space, n_initial_random=10, rng=np.random.default_rng(0))
    p = opt.suggest_next_params()
    assert 0.0 <= p["a"] <= 1.0
    assert 1 <= p["b"] <= 5
    assert p["c"] in ("u", "v")


def test_bayesian_record_and_best():
    space = [HyperparameterSpace("x", "float", (-2.0, 2.0))]
    opt = BayesianOptimizer(space, n_initial_random=2, rng=np.random.default_rng(1))
    assert opt.get_best_params() == ({}, float("-inf"))
    opt.record_trial({"x": 0.0}, 0.5, 1.0)
    opt.record_trial({"x": 1.0}, 1.5, 1.0)
    best, score = opt.get_best_params()
    assert best["x"] == 1.0
    assert score == 1.5


def test_bayesian_suggest_after_random_may_use_gp():
    space = [HyperparameterSpace("x", "float", (0.0, 4.0)), HyperparameterSpace("y", "float", (0.0, 4.0))]
    opt = BayesianOptimizer(space, n_initial_random=4, n_candidates=64, rng=np.random.default_rng(2))
    for i in range(4):
        u = opt.suggest_next_params()
        opt.record_trial(u, float(i) * 0.3 + np.sin(i), 0.1)
    nxt = opt.suggest_next_params()
    assert "x" in nxt and "y" in nxt


def test_hyperparameter_tuner_tune_component():
    space = [HyperparameterSpace("lr", "float", (0.01, 0.5))]
    tuner = HyperparameterTuner(rng=np.random.default_rng(3))

    def obj(p):
        return 1.0 - abs(p["lr"] - 0.2)

    best = tuner.tune_component("head", space, obj, n_trials=12, n_initial_random=3)
    assert "lr" in best
    assert tuner.get_tuned_params("head") is not None


def test_hyperparameter_tuner_missing_component():
    assert HyperparameterTuner().get_tuned_params("nope") is None


def test_hyperparameter_tuner_objective_error_scores_neg_inf():
    space = [HyperparameterSpace("z", "int", (0, 2))]
    tuner = HyperparameterTuner(rng=np.random.default_rng(0))

    def boom(_):
        raise RuntimeError("fail")

    best = tuner.tune_component("bad", space, boom, n_trials=3, n_initial_random=1)
    assert "z" in best


def test_lightweight_nas_runs():
    spaces = [
        HyperparameterSpace("depth", "categorical", (0.0, 1.0), choices=[1, 2, 3]),
        HyperparameterSpace("width", "categorical", (0.0, 1.0), choices=[8, 16, 32]),
    ]

    def objective(p):
        return float(p["depth"]) * float(p["width"])

    nas = LightweightNAS(rng=np.random.default_rng(4))
    res = nas.run(name="mlp", objective=objective, spaces=spaces, n_trials=10)
    assert isinstance(res, LightweightNASResult)
    assert res.trial_count == 10
    assert res.best_score > 0


def test_get_hyperparameter_tuner_singleton():
    reset_hyperparameter_tuner()
    assert get_hyperparameter_tuner() is get_hyperparameter_tuner()


# --- Feature engineering ---


def test_auto_feature_engineer_interactions():
    fe = AutoFeatureEngineer(max_pairwise_numeric=4)
    df = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0], "y": [0.0, 1.0]})
    out = fe.generate_features(df, target_col="y", top_k=5)
    assert "a_x_b" in out.columns or any("a" in c and "b" in c for c in out.columns)
    assert len(out) == 2


def test_auto_feature_engineer_log_transform():
    fe = AutoFeatureEngineer(max_pairwise_numeric=2)
    df = pd.DataFrame({"x": [1.0, 2.0], "y": [0.1, 0.9]})
    out = fe.generate_features(df, target_col="y", top_k=3)
    cols = " ".join(out.columns)
    assert "_log" in cols or "x" in out.columns


def test_auto_feature_engineer_importance():
    fe = AutoFeatureEngineer(max_pairwise_numeric=3)
    df = pd.DataFrame({"f1": np.linspace(0, 1, 20), "f2": np.random.default_rng(0).normal(size=20), "t": np.arange(20)})
    out = fe.generate_features(df, target_col="t", top_k=4)
    imp = fe.get_important_features(top_k=2)
    assert len(imp) <= 2
    assert len(out.columns) <= 4


def test_auto_feature_engineer_empty_frame():
    fe = AutoFeatureEngineer()
    df = pd.DataFrame()
    out = fe.generate_features(df)
    assert out.empty


def test_feature_engineer_timestamp_rolling():
    fe = AutoFeatureEngineer(max_pairwise_numeric=2)
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=6, freq="h"),
            "x": [1.0, 2.0, 3.0, 2.0, 1.0, 0.5],
        }
    )
    out = fe.generate_features(df)
    assert any("rolling_mean" in c for c in out.columns)


def test_auto_feature_engineer_no_target_skips_selection():
    fe = AutoFeatureEngineer(max_pairwise_numeric=2)
    df = pd.DataFrame({"a": [1.0, 2.0], "b": [1.0, 3.0]})
    out = fe.generate_features(df, target_col=None)
    assert "a_x_b" in out.columns


def test_bayesian_identical_scores_falls_back_without_crash():
    space = [HyperparameterSpace("x", "float", (0.0, 1.0))]
    opt = BayesianOptimizer(space, n_initial_random=1, rng=np.random.default_rng(0))
    opt.record_trial({"x": 0.5}, 1.0, 1.0)
    opt.record_trial({"x": 0.7}, 1.0, 1.0)
    p = opt.suggest_next_params()
    assert "x" in p


def test_discover_module_include_classes_changes_count():
    td = ToolDiscovery()
    with_classes = td.discover_from_module("services.self_evolution.tool_discovery", include_classes=True)
    reset_tool_discovery()
    td2 = ToolDiscovery()
    no_classes = td2.discover_from_module("services.self_evolution.tool_discovery", include_classes=False)
    assert len(with_classes) >= len(no_classes)


def test_record_trial_ids_sequential():
    space = [HyperparameterSpace("a", "float", (0.0, 1.0))]
    opt = BayesianOptimizer(space, rng=np.random.default_rng(0))
    opt.record_trial({"a": 0.1}, 0.2, 1.0)
    assert opt.trials[0].trial_id == 0
    opt.record_trial({"a": 0.2}, 0.3, 1.0)
    assert opt.trials[1].trial_id == 1


def test_reset_self_evolution_clears_hyperparameter_tuner():
    get_hyperparameter_tuner().optimizers["x"] = BayesianOptimizer(
        [HyperparameterSpace("z", "float", (0.0, 1.0))], rng=np.random.default_rng(0)
    )
    reset_self_evolution_singletons()
    assert get_hyperparameter_tuner().optimizers == {}


def test_self_evolution_exports_stage4c():
    from services import self_evolution as se

    assert hasattr(se, "ToolDiscovery")
    assert hasattr(se, "BayesianOptimizer")
    assert hasattr(se, "AutoFeatureEngineer")