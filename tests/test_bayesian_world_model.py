"""Tests for :mod:`services.world_model.bayesian_world_model`.

DB-free: an autouse fixture patches ``_factory_or_none`` to return ``None``
so persistence helpers short-circuit cleanly on every test.
"""

from __future__ import annotations

import math
import threading
from typing import Any
from unittest.mock import patch

import pytest

from services.world_model.bayesian_world_model import (
    STATE_VARIABLES,
    VARIABLES_BY_NAME,
    BayesianWorldModel,
    Variable,
    WorldModelOutput,
    _Belief,
    _direction_score,
    _discretise,
    _new_belief,
    _outcome_prior,
    _update_belief,
    get_status,
    predict,
    state_signature,
    update_world_model,
)


@pytest.fixture(autouse=True)
def no_db():
    """Patch DB factory to None so all tests run without a database."""
    with patch(
        "services.world_model.bayesian_world_model._factory_or_none",
        return_value=None,
    ):
        yield


# ---------------------------------------------------------------------------
# Schema / constant tests
# ---------------------------------------------------------------------------


def test_state_variables_minimum_count():
    """At least 50 variables must exist (spec says 52)."""
    assert len(STATE_VARIABLES) >= 50


def test_state_variables_names_unique():
    names = [v.name for v in STATE_VARIABLES]
    assert len(names) == len(set(names)), "Duplicate variable names"


def test_variables_by_name_covers_all():
    for v in STATE_VARIABLES:
        assert VARIABLES_BY_NAME[v.name] is v


def test_all_variable_kinds_present():
    kinds = {v.kind for v in STATE_VARIABLES}
    assert "continuous" in kinds
    assert "binary" in kinds
    assert "categorical" in kinds


def test_categorical_variables_have_categories():
    for v in STATE_VARIABLES:
        if v.kind == "categorical":
            assert len(v.categories) >= 2, f"{v.name} has <2 categories"


def test_binary_variables_have_no_categories():
    for v in STATE_VARIABLES:
        if v.kind == "binary":
            assert v.categories == (), f"{v.name} binary should have no categories"


# ---------------------------------------------------------------------------
# _discretise
# ---------------------------------------------------------------------------


def test_discretise_continuous_vlo():
    var = VARIABLES_BY_NAME["revenue_7d_trend"]  # bins=(-0.05, 0.0, 0.05)
    assert _discretise(var, -0.10) == "vlo"


def test_discretise_continuous_lo():
    var = VARIABLES_BY_NAME["revenue_7d_trend"]
    assert _discretise(var, -0.02) == "lo"


def test_discretise_continuous_hi():
    var = VARIABLES_BY_NAME["revenue_7d_trend"]
    assert _discretise(var, 0.03) == "hi"


def test_discretise_continuous_vhi():
    var = VARIABLES_BY_NAME["revenue_7d_trend"]
    assert _discretise(var, 0.10) == "vhi"


def test_discretise_binary_true():
    var = VARIABLES_BY_NAME["online_learner_health"]
    assert _discretise(var, True) == "1"
    assert _discretise(var, False) == "0"


def test_discretise_categorical_known():
    var = VARIABLES_BY_NAME["market_regime"]
    assert _discretise(var, "bull") == "bull"
    assert _discretise(var, "BEAR") == "bear"


def test_discretise_categorical_unknown_returns_first_cat():
    var = VARIABLES_BY_NAME["market_regime"]
    result = _discretise(var, "unknown_value")
    assert result == var.categories[0][:6]


def test_discretise_none_returns_question_mark():
    var = VARIABLES_BY_NAME["revenue_7d_trend"]
    assert _discretise(var, None) == "?"


# ---------------------------------------------------------------------------
# state_signature
# ---------------------------------------------------------------------------


def test_state_signature_is_12_hex_chars():
    sig = state_signature({})
    assert len(sig) == 12
    assert all(c in "0123456789abcdef" for c in sig)


def test_state_signature_order_independent():
    s1 = state_signature({"revenue_7d_trend": 0.01, "market_regime": "bull"})
    s2 = state_signature({"market_regime": "bull", "revenue_7d_trend": 0.01})
    assert s1 == s2


def test_state_signature_changes_with_different_values():
    s1 = state_signature({"revenue_7d_trend": 0.10})
    s2 = state_signature({"revenue_7d_trend": -0.10})
    assert s1 != s2


def test_state_signature_empty_is_stable():
    assert state_signature({}) == state_signature({})


# ---------------------------------------------------------------------------
# _new_belief and _update_belief
# ---------------------------------------------------------------------------


def test_new_belief_continuous_starts_at_zero():
    var = VARIABLES_BY_NAME["revenue_7d_trend"]
    b = _new_belief(var)
    assert b.n == 0 and b.mean == 0.0


def test_new_belief_binary_starts_at_one_one():
    var = VARIABLES_BY_NAME["online_learner_health"]
    b = _new_belief(var)
    assert b.alpha == 1.0 and b.beta == 1.0


def test_new_belief_categorical_has_laplace_counts():
    var = VARIABLES_BY_NAME["market_regime"]
    b = _new_belief(var)
    for cat in var.categories:
        assert b.counts[cat] == 1.0


def test_update_belief_continuous_welford_mean():
    var = VARIABLES_BY_NAME["cash_position"]
    b = _new_belief(var)
    for v in [100.0, 200.0, 300.0]:
        _update_belief(b, v)
    assert b.n == 3
    assert abs(b.mean - 200.0) < 1e-9


def test_update_belief_continuous_welford_variance():
    """Welford variance of [1, 2, 3] should be M2/n = 2/3."""
    var = VARIABLES_BY_NAME["revenue_7d_trend"]
    b = _new_belief(var)
    for v in [1.0, 2.0, 3.0]:
        _update_belief(b, v)
    variance = b.m2 / b.n
    assert abs(variance - (2.0 / 3.0)) < 1e-9


def test_update_belief_continuous_ignores_non_numeric():
    var = VARIABLES_BY_NAME["revenue_7d_trend"]
    b = _new_belief(var)
    _update_belief(b, "not_a_number")
    assert b.n == 0


def test_update_belief_binary_positive_increments_alpha():
    var = VARIABLES_BY_NAME["online_learner_health"]
    b = _new_belief(var)
    _update_belief(b, True)
    assert b.alpha == 2.0 and b.beta == 1.0 and b.n == 1


def test_update_belief_binary_negative_increments_beta():
    var = VARIABLES_BY_NAME["online_learner_health"]
    b = _new_belief(var)
    _update_belief(b, False)
    assert b.beta == 2.0 and b.alpha == 1.0


def test_update_belief_categorical_known_category():
    var = VARIABLES_BY_NAME["market_regime"]
    b = _new_belief(var)
    _update_belief(b, "bull")
    assert b.counts["bull"] == 2.0  # started at 1 (Laplace)


def test_update_belief_categorical_unknown_registers():
    var = VARIABLES_BY_NAME["market_regime"]
    b = _new_belief(var)
    _update_belief(b, "crash")
    assert "crash" in b.counts


# ---------------------------------------------------------------------------
# _Belief.as_dict
# ---------------------------------------------------------------------------


def test_belief_as_dict_continuous_has_mean_variance():
    var = VARIABLES_BY_NAME["revenue_7d_trend"]
    b = _new_belief(var)
    for v in [0.01, 0.02, 0.03]:
        _update_belief(b, v)
    d = b.as_dict()
    assert "mean" in d and "variance" in d and "stddev" in d
    assert d["n"] == 3


def test_belief_as_dict_binary_has_p():
    var = VARIABLES_BY_NAME["online_learner_health"]
    b = _new_belief(var)
    _update_belief(b, True)
    d = b.as_dict()
    assert "p" in d
    # p should be alpha / (alpha + beta) = 2 / 3
    assert abs(d["p"] - 2 / 3) < 1e-3


def test_belief_as_dict_categorical_probs_sum_to_one():
    """Probs may be rounded so allow tolerance of 1e-3."""
    var = VARIABLES_BY_NAME["market_regime"]
    b = _new_belief(var)
    d = b.as_dict()
    assert "probs" in d
    total = sum(d["probs"].values())
    assert abs(total - 1.0) < 1e-3


# ---------------------------------------------------------------------------
# _direction_score
# ---------------------------------------------------------------------------


def test_direction_score_binary_high_after_mostly_true():
    var = VARIABLES_BY_NAME["online_learner_health"]
    b = _new_belief(var)
    for _ in range(9):
        _update_belief(b, True)
    score_high = _direction_score(var, b, "high")
    score_low = _direction_score(var, b, "low")
    assert score_high > 0.8
    assert score_low < 0.2


def test_direction_score_categorical_reflects_observations():
    var = VARIABLES_BY_NAME["market_regime"]
    b = _new_belief(var)
    for _ in range(10):
        _update_belief(b, "bull")
    score = _direction_score(var, b, "bull")
    assert score > 0.7


# ---------------------------------------------------------------------------
# _outcome_prior
# ---------------------------------------------------------------------------


def test_outcome_prior_cash_crunch_with_low_cash():
    state = {"cash_position": 10_000.0, "cash_runway_months": 0.5}
    p = _outcome_prior(state, "cash_crunch_30d")
    assert p >= 0.5, "Low cash should produce elevated probability"


def test_outcome_prior_revenue_up_with_strong_signals():
    state = {
        "revenue_7d_trend": 0.10,
        "market_regime": "bull",
        "festival_proximity_days": 2.0,
        "low_stock_count": 0.0,
    }
    p = _outcome_prior(state, "revenue_up_next_week")
    assert p >= 0.5


def test_outcome_prior_unknown_outcome_returns_half():
    p = _outcome_prior({}, "nonexistent_outcome_xyz")
    assert p == 0.5


def test_outcome_prior_bounded_02_to_098():
    for outcome in ["cash_crunch_30d", "trading_drawdown_alert", "founder_burnout_risk"]:
        p = _outcome_prior({}, outcome)
        assert 0.02 <= p <= 0.98


# ---------------------------------------------------------------------------
# BayesianWorldModel (DB-free via autouse fixture)
# ---------------------------------------------------------------------------


def test_model_initialises_all_beliefs():
    model = BayesianWorldModel(organization_id=None)
    assert len(model.beliefs) == len(STATE_VARIABLES)


def test_update_from_observation_increments_evidence_count():
    model = BayesianWorldModel(organization_id=None)
    obs = {"revenue_7d_trend": 0.05, "cash_position": 500_000.0}
    result = model.update_from_observation(obs)
    assert model.evidence_count == 1
    assert result["ok"] is True


def test_update_from_observation_ignores_none_values():
    model = BayesianWorldModel(organization_id=None)
    result = model.update_from_observation({"revenue_7d_trend": None})
    assert model.evidence_count == 0  # nothing actually updated


def test_update_from_observation_updates_belief():
    model = BayesianWorldModel(organization_id=None)
    model.update_from_observation({"cash_position": 100_000.0})
    belief = model.beliefs["cash_position"]
    assert belief.n == 1
    assert abs(belief.mean - 100_000.0) < 1e-6


def test_update_sets_last_signature():
    model = BayesianWorldModel(organization_id=None)
    model.update_from_observation({"revenue_7d_trend": 0.01})
    assert model.last_signature is not None and len(model.last_signature) == 12


def test_get_state_vector_returns_dict_with_all_variables():
    model = BayesianWorldModel(organization_id=None)
    sv = model.get_state_vector()
    assert set(sv.keys()) == {v.name for v in STATE_VARIABLES}


def test_get_belief_distribution_has_all_variables():
    model = BayesianWorldModel(organization_id=None)
    bd = model.get_belief_distribution()
    assert len(bd) == len(STATE_VARIABLES)


def test_predict_outcome_returns_expected_keys():
    model = BayesianWorldModel(organization_id=None)
    pred = model.predict_outcome("trading_drawdown_alert")
    for key in ("outcome", "p", "p_prior", "p_evidence", "evidence_n", "state_signature", "drivers"):
        assert key in pred, f"Missing key: {key}"


def test_predict_outcome_p_bounded():
    model = BayesianWorldModel(organization_id=None)
    pred = model.predict_outcome("cash_crunch_30d")
    assert 0.01 <= pred["p"] <= 0.99


def test_predict_outcome_with_conditions_overrides_state():
    """Compare high vs low cash — conditions should meaningfully shift probability."""
    model = BayesianWorldModel(organization_id=None)
    p_high_cash = model.predict_outcome(
        "cash_crunch_30d", conditions={"cash_position": 3_000_000.0}
    )["p"]
    p_low_cash = model.predict_outcome(
        "cash_crunch_30d", conditions={"cash_position": 5_000.0}
    )["p"]
    assert p_low_cash >= p_high_cash, "Lower cash should increase cash crunch probability"


def test_predict_all_business_outcomes_covers_all():
    model = BayesianWorldModel(organization_id=None)
    preds = model.predict_all_business_outcomes()
    from services.world_model.bayesian_world_model import _OUTCOME_INFLUENCES

    assert set(preds.keys()) == set(_OUTCOME_INFLUENCES.keys())


def test_snapshot_without_db_returns_dict():
    model = BayesianWorldModel(organization_id=None)
    out = model.snapshot()
    assert out["ok"] is True
    assert "state_signature" in out


def test_update_world_model_module_level():
    result = update_world_model(organization_id=None)
    assert result["ok"] is True


def test_predict_module_level_all_outcomes():
    result = predict(organization_id=None)
    assert result["ok"] is True
    assert "predictions" in result


def test_predict_module_level_single_outcome():
    result = predict(organization_id=None, outcome="founder_burnout_risk")
    assert result["ok"] is True
    assert "prediction" in result
    assert result["prediction"]["outcome"] == "founder_burnout_risk"


def test_get_status_no_db():
    s = get_status()
    assert s["variable_count"] == len(STATE_VARIABLES)
    assert s["snapshot_count"] == 0


def test_concurrent_updates_do_not_raise():
    """Verify that concurrent update_from_observation calls are safe (no exceptions)."""
    model = BayesianWorldModel(organization_id=None)
    errors: list[str] = []

    def worker(value: float) -> None:
        try:
            model.update_from_observation({"cash_position": value})
        except Exception as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=worker, args=(float(i * 10_000),)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Errors during concurrent updates: {errors}"
    assert model.evidence_count >= 1


def test_welford_stability_large_values():
    """Welford running mean should stay accurate for large INR values."""
    model = BayesianWorldModel(organization_id=None)
    values = [1_000_000.0 + i * 1_000.0 for i in range(100)]
    for v in values:
        model.update_from_observation({"cash_position": v})
    expected_mean = sum(values) / len(values)
    actual_mean = model.beliefs["cash_position"].mean
    assert abs(actual_mean - expected_mean) < 1.0  # within ₹1


def test_update_with_empty_observations_does_not_increment_count():
    model = BayesianWorldModel(organization_id=None)
    model.update_from_observation({})
    assert model.evidence_count == 0


def test_update_with_unknown_variable_name_is_ignored():
    model = BayesianWorldModel(organization_id=None)
    model.update_from_observation({"totally_unknown_variable_xyz": 99.9})
    assert model.evidence_count == 0


def test_top_drivers_are_sorted_by_contribution():
    model = BayesianWorldModel(organization_id=None)
    model.update_from_observation(
        {"drawdown_pct": 0.15, "volatility_30d": 0.30, "vix_proxy": 30.0}
    )
    pred = model.predict_outcome("trading_drawdown_alert")
    drivers = pred["drivers"]
    contributions = [d["contribution"] for d in drivers]
    assert contributions == sorted(contributions, reverse=True)


def test_predict_outcome_empty_state_still_returns_valid():
    """Even with no observations, predictions must be valid."""
    model = BayesianWorldModel(organization_id=None)
    pred = model.predict_outcome("revenue_up_next_week")
    assert 0.01 <= pred["p"] <= 0.99
    assert isinstance(pred["drivers"], list)
