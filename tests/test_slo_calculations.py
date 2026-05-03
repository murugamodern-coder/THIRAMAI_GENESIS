"""Unit tests for SLO / error-budget math used in recording rules (docs + mental model)."""

from __future__ import annotations


def test_burn_rate_calculation() -> None:
    target_slo = 0.999
    error_budget = 1 - target_slo
    current_error_rate = 0.01
    burn_rate = current_error_rate / error_budget
    assert abs(burn_rate - 10.0) < 1e-9
    hours_to_exhaustion = 720 / burn_rate
    assert abs(hours_to_exhaustion - 72.0) < 1e-6


def test_fast_burn_threshold_hours() -> None:
    fast_burn_threshold = 14.4
    hours_to_exhaustion = 720 / fast_burn_threshold
    assert abs(hours_to_exhaustion - 50.0) < 0.001


def test_error_budget_remaining() -> None:
    target_slo = 0.999
    current_availability = 0.998
    budget_consumed = (1 - current_availability) / (1 - target_slo)
    budget_remaining = 1 - budget_consumed
    assert budget_consumed == 2.0
    assert budget_remaining == -1.0


def test_slo_compliance_over_time() -> None:
    successful_requests = 999_000
    failed_requests = 1000
    total_requests = successful_requests + failed_requests
    availability = successful_requests / total_requests
    assert abs(availability - 0.999) < 0.0001


def test_latency_slo_percentile() -> None:
    latencies = [0.1] * 95 + [0.8] * 5
    latencies_sorted = sorted(latencies)
    p95_index = int(len(latencies_sorted) * 0.95)
    p95_latency = latencies_sorted[p95_index]
    assert p95_latency == 0.8
    slo_target_ms = 500
    assert p95_latency * 1000 > slo_target_ms
