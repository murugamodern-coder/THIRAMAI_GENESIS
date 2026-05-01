"""Tests for :mod:`services.ml.online_learner`.

DB-free and file-system light: session factory and model registry are patched
inline using context managers so each test is self-contained and explicit.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from services.ml.online_learner import (
    KMEANS_MODEL_NAME,
    ONLINE_MODEL_NAME,
    _ensure_online_model,
    _features_for,
    _label_from_actual,
    _new_sgd_classifier,
    get_status,
    online_available,
    online_cluster_features,
    predict_and_record,
)


# ---------------------------------------------------------------------------
# Capability flags
# ---------------------------------------------------------------------------


def test_online_available_returns_bool():
    assert isinstance(online_available(), bool)


def test_sklearn_actually_available():
    """scikit-learn is in requirements-base.txt — must be importable."""
    assert online_available() is True, "scikit-learn not installed"


# ---------------------------------------------------------------------------
# _label_from_actual
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "actual, expected",
    [
        ({"success": True}, 1),
        ({"success": False}, 0),
        ({"outcome": "success"}, 1),
        ({"outcome": "ok"}, 1),
        ({"outcome": "approved"}, 1),
        ({"outcome": "applied"}, 1),
        ({"outcome": "failure"}, 0),
        ({"outcome": "rejected"}, 0),
        ({"outcome": "failed"}, 0),
        ({"outcome": "error"}, 0),
        ({"outcome": "unknown_state"}, None),
        (None, None),
        ("not_a_dict", None),
        ({}, None),
    ],
)
def test_label_from_actual_all_cases(actual, expected):
    assert _label_from_actual(actual) == expected


# ---------------------------------------------------------------------------
# _new_sgd_classifier
# ---------------------------------------------------------------------------


def test_new_sgd_classifier_is_not_none():
    clf = _new_sgd_classifier()
    assert clf is not None


def test_new_sgd_classifier_has_expected_params():
    clf = _new_sgd_classifier()
    assert clf.loss == "log_loss"
    assert clf.alpha == pytest.approx(1e-4)


# ---------------------------------------------------------------------------
# _ensure_online_model — cold start
# ---------------------------------------------------------------------------


def test_ensure_online_model_cold_start_has_model():
    with patch("services.ml.online_learner.ModelRegistry.get_active", return_value=None), \
         patch("services.ml.online_learner.ModelRegistry.get_latest", return_value=None):
        payload = _ensure_online_model()
    assert "model" in payload
    assert payload["samples_seen"] == 0
    assert "feature_names" in payload
    assert len(payload["feature_names"]) > 0


def test_ensure_online_model_cold_start_accuracy_zero():
    with patch("services.ml.online_learner.ModelRegistry.get_active", return_value=None), \
         patch("services.ml.online_learner.ModelRegistry.get_latest", return_value=None):
        payload = _ensure_online_model()
    assert payload["rolling_accuracy"] == 0.0


# ---------------------------------------------------------------------------
# _features_for
# ---------------------------------------------------------------------------


def test_features_for_returns_list_of_floats():
    when = datetime(2025, 1, 1, 9, 30, tzinfo=timezone.utc)
    feats = _features_for("sell_stock", when, {})
    assert isinstance(feats, list)
    assert all(isinstance(f, (int, float)) for f in feats)


def test_features_for_non_empty():
    when = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)
    feats = _features_for("sell_stock", when, {})
    assert len(feats) > 0


def test_features_for_same_inputs_same_output():
    when = datetime(2025, 6, 15, 10, 0, tzinfo=timezone.utc)
    ctx = {"past_success_rate": 0.7}
    f1 = _features_for("reorder_stock", when, ctx)
    f2 = _features_for("reorder_stock", when, ctx)
    assert f1 == f2


def test_features_for_past_success_rate_affects_output():
    when = datetime(2025, 6, 15, 10, 0, tzinfo=timezone.utc)
    f_low = _features_for("reorder_stock", when, {"past_success_rate": 0.1})
    f_high = _features_for("reorder_stock", when, {"past_success_rate": 0.9})
    assert f_low != f_high


def test_features_for_different_action_types_may_differ():
    when = datetime(2025, 6, 15, 10, 0, tzinfo=timezone.utc)
    f1 = _features_for("sell_stock", when, {})
    f2 = _features_for("reorder_stock", when, {})
    # Different action type hashes → at least one feature value differs
    assert f1 != f2


# ---------------------------------------------------------------------------
# predict_and_record — DB-free (no row written)
# ---------------------------------------------------------------------------


def test_predict_and_record_db_unavailable_ok():
    with patch("services.ml.online_learner._factory_or_none", return_value=None), \
         patch("services.ml.online_learner.ModelRegistry.get_active", return_value=None), \
         patch("services.ml.online_learner.ModelRegistry.get_latest", return_value=None):
        result = predict_and_record(action_type="sell_stock", organization_id=None)
    assert result["ok"] is True
    assert 0.0 <= result["probability"] <= 1.0
    assert result["prediction_id"] is None  # no DB
    assert isinstance(result["method"], str)


def test_predict_and_record_uses_baseline_on_cold_start():
    with patch("services.ml.online_learner._factory_or_none", return_value=None), \
         patch("services.ml.online_learner.ModelRegistry.get_active", return_value=None), \
         patch("services.ml.online_learner.ModelRegistry.get_latest", return_value=None):
        result = predict_and_record(action_type="sell_stock")
    assert "warmup" in result["method"] or "baseline" in result["method"]


def test_predict_and_record_probability_in_range():
    with patch("services.ml.online_learner._factory_or_none", return_value=None), \
         patch("services.ml.online_learner.ModelRegistry.get_active", return_value=None), \
         patch("services.ml.online_learner.ModelRegistry.get_latest", return_value=None):
        for action in ["sell_stock", "reorder_stock", "schedule_meeting", "unknown_action"]:
            r = predict_and_record(action_type=action)
            assert 0.0 <= r["probability"] <= 1.0, f"out of range for {action}"


def test_predict_and_record_respects_when_parameter():
    when = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    with patch("services.ml.online_learner._factory_or_none", return_value=None), \
         patch("services.ml.online_learner.ModelRegistry.get_active", return_value=None), \
         patch("services.ml.online_learner.ModelRegistry.get_latest", return_value=None):
        result = predict_and_record(action_type="sell_stock", when=when)
    assert result["ok"] is True


def test_predict_and_record_with_context():
    ctx = {"past_success_rate": 0.8, "inventory_level": 50}
    with patch("services.ml.online_learner._factory_or_none", return_value=None), \
         patch("services.ml.online_learner.ModelRegistry.get_active", return_value=None), \
         patch("services.ml.online_learner.ModelRegistry.get_latest", return_value=None):
        result = predict_and_record(action_type="reorder_stock", context=ctx)
    assert result["ok"] is True


# ---------------------------------------------------------------------------
# online_cluster_features — drift detection
# ---------------------------------------------------------------------------


def test_online_cluster_features_returns_ok():
    feature_rows = [[float(i), float(i + 1)] for i in range(20)]
    with patch("services.ml.online_learner.ModelRegistry.get_active", return_value=None), \
         patch("services.ml.online_learner.ModelRegistry.get_latest", return_value=None), \
         patch("services.ml.online_learner.ModelRegistry.register"), \
         patch("services.ml.online_learner.model_artifact_path", return_value="/tmp/km.joblib"), \
         patch("services.ml.online_learner.next_version", return_value="v1"), \
         patch("joblib.dump"):
        result = online_cluster_features(feature_rows=feature_rows, n_clusters=3)
    assert result["ok"] is True
    assert result["samples"] == 20
    assert isinstance(result["centers"], list)
    assert result["n_clusters"] == 3


def test_online_cluster_features_empty_input_returns_ok():
    result = online_cluster_features(feature_rows=[])
    assert result["ok"] is True
    assert result["samples"] == 0
    assert result["centers"] == []


def test_online_cluster_features_n_clusters_clamped():
    """n_clusters=1 should be clamped to 2 by max(2, ...)."""
    feature_rows = [[float(i)] for i in range(10)]
    with patch("services.ml.online_learner.ModelRegistry.get_active", return_value=None), \
         patch("services.ml.online_learner.ModelRegistry.get_latest", return_value=None), \
         patch("services.ml.online_learner.ModelRegistry.register"), \
         patch("services.ml.online_learner.model_artifact_path", return_value="/tmp/km.joblib"), \
         patch("services.ml.online_learner.next_version", return_value="v1"), \
         patch("joblib.dump"):
        result = online_cluster_features(feature_rows=feature_rows, n_clusters=1)
    assert result["ok"] is True


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


def test_get_status_returns_expected_keys():
    with patch("services.ml.online_learner.ModelRegistry.get_active", return_value=None), \
         patch("services.ml.online_learner.ModelRegistry.get_latest", return_value=None):
        status = get_status()
    for key in ("available", "samples_seen", "rolling_accuracy", "version"):
        assert key in status, f"Missing key: {key}"


def test_get_status_available_true_when_sklearn():
    with patch("services.ml.online_learner.ModelRegistry.get_active", return_value=None), \
         patch("services.ml.online_learner.ModelRegistry.get_latest", return_value=None):
        status = get_status()
    assert status["available"] is True


def test_get_status_samples_seen_non_negative():
    with patch("services.ml.online_learner.ModelRegistry.get_active", return_value=None), \
         patch("services.ml.online_learner.ModelRegistry.get_latest", return_value=None):
        status = get_status()
    assert status["samples_seen"] >= 0


def test_get_status_accuracy_in_range():
    with patch("services.ml.online_learner.ModelRegistry.get_active", return_value=None), \
         patch("services.ml.online_learner.ModelRegistry.get_latest", return_value=None):
        status = get_status()
    assert 0.0 <= status["rolling_accuracy"] <= 1.0


# ---------------------------------------------------------------------------
# Partial_fit round-trip (no DB, no disk — pure sklearn)
# ---------------------------------------------------------------------------


def test_sgd_partial_fit_converges_on_trivial_dataset():
    """SGDClassifier.partial_fit should train on linearly separable data."""
    import numpy as np
    from sklearn.linear_model import SGDClassifier

    clf = _new_sgd_classifier()
    X = np.array([[0.0] * 6, [1.0] * 6] * 20, dtype=float)
    y = np.array([0, 1] * 20, dtype=int)
    for i in range(0, len(X), 2):
        clf.partial_fit(X[i : i + 2], y[i : i + 2], classes=np.array([0, 1]))
    preds = clf.predict(np.array([[0.05] * 6, [0.95] * 6]))
    assert preds[0] == 0
    assert preds[1] == 1


def test_sgd_predict_proba_returns_two_classes():
    import numpy as np

    clf = _new_sgd_classifier()
    X = np.array([[0.0] * 6] * 5 + [[1.0] * 6] * 5, dtype=float)
    y = np.array([0] * 5 + [1] * 5, dtype=int)
    clf.partial_fit(X, y, classes=np.array([0, 1]))
    proba = clf.predict_proba(np.array([[0.5] * 6]))
    assert proba.shape == (1, 2)
    assert abs(sum(proba[0]) - 1.0) < 1e-6
