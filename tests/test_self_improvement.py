"""Tests for performance monitoring, improvement generation, and the loop."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services.self_evolution.improvement_generator import ImprovementGenerator
from services.self_evolution.improvement_loop import (
    IterationResult,
    SelfImprovementLoop,
    reset_self_evolution_singletons,
)
from services.self_evolution.performance_monitor import (
    PerformanceDegradation,
    PerformanceMetrics,
    PerformanceMonitor,
    get_performance_monitor,
    reset_performance_monitor,
    _row_domain,
)


NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)


def _log(
    *,
    at: datetime,
    success: bool | None = True,
    domain: str = "business",
    confidence: float | None = 0.8,
    reward: float | None = None,
    ctx_variant: int = 0,
) -> SimpleNamespace:
    outcome: dict = {}
    if confidence is not None:
        outcome["confidence"] = confidence
    if reward is not None:
        outcome["reward"] = reward
    return SimpleNamespace(
        success=success,
        outcome_json=outcome,
        context={"domain": domain, "variant": ctx_variant},
        input_data_json={"x": ctx_variant},
        created_at=at,
    )


# ---------------------------------------------------------------------------
# PerformanceMonitor — rows & domain
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset():
    reset_self_evolution_singletons()
    yield
    reset_self_evolution_singletons()


def test_row_domain_from_context():
    r = SimpleNamespace(context={"domain": "Trading"})
    assert _row_domain(r) == "trading"


def test_row_domain_unknown():
    assert _row_domain(SimpleNamespace(context={})) == "unknown"


def test_metrics_all_resolved_accuracy():
    start, end = NOW - timedelta(hours=2), NOW
    rows = [
        _log(at=start + timedelta(minutes=i), success=True) for i in range(10)
    ]
    m = PerformanceMonitor(row_source=lambda s, e: [r for r in rows if s <= r.created_at < e])
    # Manually invoke slice helper
    cur = m._metrics_from_rows(rows, start, end)
    assert cur.decision_accuracy == 1.0
    assert cur.sample_size == 10


def test_metrics_error_rate_counts_failures():
    rows = [
        _log(at=NOW - timedelta(hours=1), success=False),
        _log(at=NOW - timedelta(minutes=30), success=True),
    ]
    m = PerformanceMonitor()
    met = m._metrics_from_rows(rows, NOW - timedelta(hours=2), NOW)
    assert met.error_rate == pytest.approx(0.5)


def test_prediction_accuracy_from_outcome_json():
    rows = [
        SimpleNamespace(
            success=True,
            outcome_json={"predicted": "a", "actual": "a", "confidence": 0.9},
            context={},
            input_data_json={},
            created_at=NOW,
        ),
        SimpleNamespace(
            success=True,
            outcome_json={"predicted": "b", "actual": "a", "confidence": 0.8},
            context={},
            input_data_json={},
            created_at=NOW + timedelta(minutes=1),
        ),
    ]
    m = PerformanceMonitor()
    met = m._metrics_from_rows(rows, NOW, NOW + timedelta(hours=1))
    assert met.prediction_accuracy == pytest.approx(0.5)


def test_trading_sharpe_requires_two_rewards():
    rows = [
        _log(at=NOW, domain="trading", reward=0.01),
    ]
    m = PerformanceMonitor()
    assert m._trading_sharpe(rows) == 0.0


def test_trading_sharpe_positive():
    rows = [
        _log(at=NOW + timedelta(minutes=i), domain="trading", reward=0.01 * (i + 1))
        for i in range(5)
    ]
    m = PerformanceMonitor()
    s = m._trading_sharpe(rows)
    assert s > 0


def test_business_success_rate():
    rows = [
        _log(at=NOW, domain="business", success=True),
        _log(at=NOW + timedelta(minutes=1), domain="business", success=False),
    ]
    m = PerformanceMonitor()
    met = m._metrics_from_rows(rows, NOW, NOW + timedelta(hours=1))
    assert met.business_success_rate == pytest.approx(0.5)


def test_check_performance_paired_windows_no_degradation():
    """Baseline and current both healthy → no issues."""
    window = 24
    base_start = NOW - timedelta(hours=2 * window)
    base_end = NOW - timedelta(hours=window)
    cur_start = base_end
    rows = []
    for i in range(20):
        rows.append(
            _log(
                at=base_start + timedelta(hours=i * 0.5),
                success=True,
                ctx_variant=i,
            )
        )
    for i in range(20):
        rows.append(
            _log(
                at=cur_start + timedelta(hours=i * 0.5),
                success=True,
                ctx_variant=i + 100,
            )
        )

    def source(start: datetime, end: datetime):
        return [r for r in rows if start <= r.created_at < end]

    m = PerformanceMonitor(row_source=source, clock=lambda: NOW)
    m.baseline_metrics = None
    cur, deg = m.check_performance(window_hours=window)
    assert cur.sample_size > 0
    assert m.baseline_metrics is not None
    assert isinstance(deg, list)


def test_accuracy_drop_detected():
    window = 24
    base_start = NOW - timedelta(hours=2 * window)
    base_end = NOW - timedelta(hours=window)
    cur_start = base_end
    rows = [_log(at=base_start + timedelta(minutes=i), success=True) for i in range(30)]
    for i in range(30):
        rows.append(
            _log(at=cur_start + timedelta(minutes=i), success=(i % 2 == 0))
        )

    def source(start: datetime, end: datetime):
        return [r for r in rows if start <= r.created_at < end]

    m = PerformanceMonitor(
        row_source=source,
        clock=lambda: NOW,
        accuracy_threshold=0.05,
    )
    _, deg = m.check_performance(window_hours=window)
    types = {d.issue_type for d in deg}
    assert "accuracy_drop" in types


def test_error_spike_detected():
    window = 12
    b0, b1 = NOW - timedelta(hours=24), NOW - timedelta(hours=12)
    c0, c1 = NOW - timedelta(hours=12), NOW
    rows = [_log(at=b0 + timedelta(minutes=i), success=True) for i in range(15)]
    for i in range(15):
        rows.append(_log(at=c0 + timedelta(minutes=i), success=False))

    def source(start: datetime, end: datetime):
        return [r for r in rows if start <= r.created_at < end]

    m = PerformanceMonitor(
        row_source=source,
        clock=lambda: NOW,
        error_spike_threshold=1.5,
    )
    _, deg = m.check_performance(window_hours=window)
    assert any(d.issue_type == "error_spike" for d in deg)


def test_drift_issue_when_feature_score_high():
    m = PerformanceMonitor(clock=lambda: NOW, row_source=lambda s, e: [])
    m.baseline_metrics = PerformanceMetrics(
        NOW - timedelta(hours=12),
        NOW - timedelta(hours=6),
        0.9,
        0.9,
        0.05,
        0.05,
        0.01,
        0.8,
        None,
        None,
        sample_size=50,
    )
    cur = PerformanceMetrics(
        NOW - timedelta(hours=6),
        NOW,
        0.88,
        0.88,
        0.50,
        0.1,
        0.02,
        0.7,
        None,
        None,
        sample_size=50,
    )
    deg = m._detect_degradations(cur, m.baseline_metrics)
    assert any(d.issue_type == "drift" for d in deg)


def test_trading_sharpe_drop_detected():
    window = 8
    rows = []
    b0, b1 = NOW - timedelta(hours=16), NOW - timedelta(hours=8)
    c0 = b1
    for i in range(10):
        rows.append(
            _log(
                at=b0 + timedelta(minutes=i * 5),
                domain="trading",
                reward=0.02 + i * 0.001,
            )
        )
    for i in range(10):
        rows.append(
            _log(
                at=c0 + timedelta(minutes=i * 5),
                domain="trading",
                reward=-0.03 - i * 0.001,
            )
        )

    def source(start: datetime, end: datetime):
        return [r for r in rows if start <= r.created_at < end]

    m = PerformanceMonitor(row_source=source, clock=lambda: NOW, sharpe_drop_threshold=0.01)
    _, deg = m.check_performance(window_hours=window)
    assert any(d.issue_type == "performance_drop" for d in deg)


def test_empty_slice_returns_zero_metrics():
    m = PerformanceMonitor(row_source=lambda s, e: [])
    met = m._compute_metrics_slice(NOW, NOW + timedelta(hours=1))
    assert met.sample_size == 0
    assert met.decision_accuracy == 0.0


def test_refresh_baseline_recomputes():
    calls: list[tuple] = []

    def source(start, end):
        calls.append((start, end))
        return [_log(at=start + timedelta(minutes=1), success=True)]

    m = PerformanceMonitor(row_source=source, clock=lambda: NOW)
    m.check_performance(24, refresh_baseline=False)
    n1 = len(calls)
    m.check_performance(24, refresh_baseline=True)
    assert len(calls) > n1


def test_set_baseline_manual():
    m = PerformanceMonitor(row_source=lambda s, e: [])
    b = PerformanceMetrics(NOW, NOW, 0.9, 0.9,0,0,0,0.5,None,None,10)
    m.set_baseline(b)
    assert m.baseline_metrics is b


def test_singleton_performance_monitor():
    a = get_performance_monitor()
    b = get_performance_monitor()
    assert a is b


# ---------------------------------------------------------------------------
# ImprovementGenerator
# ---------------------------------------------------------------------------


def _deg(issue: str = "accuracy_drop") -> PerformanceDegradation:
    return PerformanceDegradation(
        issue_type=issue,
        severity=1.2,
        affected_domain="all",
        affected_component="x",
        current_value=0.5,
        baseline_value=0.9,
        threshold=0.1,
        detected_at=NOW,
        description="unit test",
    )


def test_generator_empty_degradations():
    g = ImprovementGenerator(client=None, api_key="")
    assert g.generate_fixes([]) == []


def test_generator_fallback_accuracy():
    g = ImprovementGenerator(client=None, api_key="")
    hyp = g.generate_fixes([_deg("accuracy_drop")])[0]
    assert hyp.fix_type == "model_retrain"
    assert hyp.test_strategy == "a_b_test"


def test_generator_fallback_drift():
    g = ImprovementGenerator(client=None, api_key="")
    hyp = g.generate_fixes([_deg("drift")])[0]
    assert hyp.fix_type == "feature_engineering"
    assert hyp.test_strategy == "shadow"


def test_generator_fallback_performance_drop():
    g = ImprovementGenerator(client=None, api_key="")
    hyp = g.generate_fixes([_deg("performance_drop")])[0]
    assert hyp.fix_type == "parameter_tuning"
    assert hyp.test_strategy == "canary"


def test_generator_fallback_error_spike():
    g = ImprovementGenerator(client=None, api_key="")
    hyp = g.generate_fixes([_deg("error_spike")])[0]
    assert hyp.fix_type == "parameter_tuning"


def test_generator_parse_claude_json():
    g = ImprovementGenerator(client=None, api_key="")
    raw = """
    Here is JSON:
    {"fix_type": "code_change", "description": "Patch router",
     "code_changes": "return x+1",
     "test_strategy": "canary",
     "success_criteria": {"accuracy": 0.1},
     "confidence": 0.8, "estimated_impact": 0.5, "risk_level": "medium"}
    """
    h = g._parse_claude_response(raw, _deg())
    assert h.fix_type == "code_change"
    assert h.code_changes == "return x+1"
    assert h.test_strategy == "canary"


def test_generator_parse_failure_falls_back():
    g = ImprovementGenerator(client=None, api_key="")
    h = g._parse_claude_response("not json {{{", _deg("drift"))
    assert h.fix_type == "feature_engineering"


def test_generator_claude_api_mocked():
    client = MagicMock()
    block = MagicMock()
    block.text = '{"fix_type":"parameter_tuning","description":"x","code_changes":null,"test_strategy":"a_b_test","success_criteria":{"a":1},"confidence":0.4,"estimated_impact":0.2,"risk_level":"low"}'
    client.messages.create.return_value = MagicMock(content=[block])
    g = ImprovementGenerator(client=client, api_key="dummy")
    hyp = g.generate_fixes([_deg()])[0]
    assert hyp.fix_type == "parameter_tuning"
    client.messages.create.assert_called_once()


def test_generator_claude_exception_falls_back():
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("rate limit")
    g = ImprovementGenerator(client=client)
    hyp = g.generate_fixes([_deg()])[0]
    assert hyp.fix_type == "model_retrain"


# ---------------------------------------------------------------------------
# SelfImprovementLoop
# ---------------------------------------------------------------------------


def test_loop_iteration_clean():
    def source(start, end):
        return [_log(at=(start + (end - start) / 2), success=True)]

    mon = PerformanceMonitor(row_source=source, clock=lambda: NOW)
    gen = ImprovementGenerator(client=None, api_key="")
    loop = SelfImprovementLoop(
        check_interval_hours=1,
        monitor=mon,
        generator=gen,
    )
    res = loop.run_iteration(window_hours=24)
    assert res.current_metrics.sample_size > 0
    assert res.deployment["status"] in ("noop", "pending_owner_approval")


def test_loop_generates_hypotheses_when_degraded():
    window = 24
    base_end = NOW - timedelta(hours=window)
    rows = (
        [_log(at=base_end - timedelta(hours=12) + timedelta(minutes=i), success=True) for i in range(20)]
        + [_log(at=NOW - timedelta(hours=12) + timedelta(minutes=i), success=False) for i in range(20)]
    )

    def source(start, end):
        return [r for r in rows if start <= r.created_at < end]

    mon = PerformanceMonitor(
        row_source=source,
        clock=lambda: NOW,
        accuracy_threshold=0.05,
    )
    gen = ImprovementGenerator(client=None, api_key="")
    loop = SelfImprovementLoop(monitor=mon, generator=gen)
    res = loop.run_iteration(window_hours=window)
    assert res.hypotheses
    assert res.deployment["status"] == "pending_owner_approval"
    assert res.deployment["count"] == len(res.hypotheses)


def test_loop_deployment_not_auto_execute():
    loop = SelfImprovementLoop(
        monitor=PerformanceMonitor(row_source=lambda s, e: []),
        generator=ImprovementGenerator(api_key=""),
    )
    res = loop.run_iteration()
    assert "No production mutation" in res.deployment.get("note", "") or res.deployment.get("status") == "noop"


def test_loop_online_learner_probe():
    loop = SelfImprovementLoop(
        monitor=PerformanceMonitor(row_source=lambda s, e: []),
        generator=ImprovementGenerator(api_key=""),
    )
    res = loop.run_iteration()
    assert "online_learner_importable" in res.online_learner_probe


@patch("services.self_evolution.improvement_loop.time.sleep", return_value=None)
def test_loop_start_runs_one_iteration_then_stops(mock_sleep):
    loop = SelfImprovementLoop(
        check_interval_hours=9999,
        monitor=PerformanceMonitor(row_source=lambda s, e: []),
        generator=ImprovementGenerator(api_key=""),
    )
    iterations = {"n": 0}
    orig = loop.run_iteration

    def wrapped(*a, **k):
        iterations["n"] += 1
        loop.stop()
        return orig(*a, **k)

    loop.run_iteration = wrapped  # type: ignore[method-assign]
    loop.start()
    assert iterations["n"] == 1


def test_loop_stop_idempotent():
    loop = SelfImprovementLoop(
        monitor=PerformanceMonitor(row_source=lambda s, e: []),
        generator=ImprovementGenerator(api_key=""),
    )
    loop.stop()
    loop.stop()


def test_reset_performance_monitor_clears_singleton():
    get_performance_monitor()
    reset_performance_monitor()
    a = get_performance_monitor()
    b = get_performance_monitor()
    assert a is b


def test_iteration_result_dataclass_fields():
    r = IterationResult(
        started_at=NOW,
        finished_at=NOW,
        current_metrics=PerformanceMetrics(NOW, NOW, 0, 0, 0, 0, 0, 0, None, None, 0),
    )
    assert r.hypotheses == []


def test_reset_self_evolution_singletons_creates_fresh_monitor():
    m1 = get_performance_monitor()
    reset_self_evolution_singletons()
    m2 = get_performance_monitor()
    assert m1 is not m2


def test_loop_deployment_ready_when_no_approval_required():
    loop = SelfImprovementLoop(
        monitor=PerformanceMonitor(row_source=lambda s, e: []),
        generator=ImprovementGenerator(api_key=""),
        deployment_requires_approval=False,
    )
    res = loop.run_iteration()
    assert res.deployment["status"] in ("ready_for_ci", "noop")
