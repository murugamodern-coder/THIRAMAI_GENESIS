"""AI quality tracker unit tests."""

from __future__ import annotations

from services.ai_quality_tracker import DecisionQualityTracker, reset_quality_tracker_for_tests


def test_tracker_window_and_baseline() -> None:
    reset_quality_tracker_for_tests()
    t = DecisionQualityTracker(window_size=200)
    for i in range(50):
        t.record_decision(action="analyze", confidence=0.7, source="policy_engine", metadata={})
    out = t.establish_baseline()
    assert out.get("ok") is False

    for i in range(60):
        t.record_decision(action="analyze", confidence=0.7, source="policy_engine", metadata={})
    out = t.establish_baseline()
    assert out.get("ok") is True

    m = t.get_quality_metrics()
    assert m.get("status") == "ok"
    assert "action_distribution" in m
    assert m["confidence"]["mean"] == 0.7


def test_anomaly_low_confidence() -> None:
    t = DecisionQualityTracker(window_size=500)
    t._min_baseline = 5  # type: ignore[attr-defined]
    for i in range(10):
        t.record_decision(action="analyze", confidence=0.7, source="policy_engine", metadata={})
    before = t.anomaly_count
    t.record_decision(action="analyze", confidence=0.05, source="policy_engine", metadata={})
    assert t.anomaly_count > before
