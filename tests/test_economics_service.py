"""Economics / Business OS helpers (no DB required when DATABASE_URL unset)."""

from __future__ import annotations

from services.business_snapshot_service import build_business_snapshot, daily_sales_target_inr
from services.economics_service import get_business_margin


def test_get_business_margin_without_database(monkeypatch):
    import services.economics_service as econ

    monkeypatch.setattr(econ, "get_session_factory", lambda: None)
    out = get_business_margin(1)
    assert out.get("ok") is False


def test_build_business_snapshot_without_database(monkeypatch):
    import services.business_snapshot_service as bss

    monkeypatch.setattr(bss, "get_session_factory", lambda: None)
    snap = build_business_snapshot(1)
    assert snap.get("ok") is False


def test_daily_sales_target_env(monkeypatch):
    monkeypatch.setenv("THIRAMAI_DAILY_SALES_TARGET_INR", "50000")
    assert daily_sales_target_inr() == __import__("decimal").Decimal("50000.00")


def test_infra_scaling_budget_unset_allows_scale(monkeypatch):
    import services.economics_service as econ

    monkeypatch.delenv("THIRAMAI_OPERATIONAL_INFRA_BUDGET_INR", raising=False)
    out = econ.infra_scaling_budget_check(1, current_worker_nodes=2)
    assert out.get("allow_scale_up") is True
    assert out.get("budget_configured") is False


def test_infra_scaling_budget_blocks_over_cap(monkeypatch):
    import services.economics_service as econ

    monkeypatch.setenv("THIRAMAI_OPERATIONAL_INFRA_BUDGET_INR", "1000")
    monkeypatch.setenv("THIRAMAI_WORKER_MONTHLY_COST_INR_EST", "500")
    out = econ.infra_scaling_budget_check(1, current_worker_nodes=2)
    assert out.get("allow_scale_up") is False
    assert "exceed" in (out.get("reason") or "").lower()


def test_infra_scaling_budget_remaining(monkeypatch):
    import services.economics_service as econ

    monkeypatch.setenv("THIRAMAI_OPERATIONAL_INFRA_BUDGET_INR", "10000")
    monkeypatch.setenv("THIRAMAI_WORKER_MONTHLY_COST_INR_EST", "500")
    out = econ.infra_scaling_budget_remaining(1, current_worker_nodes=3)
    assert out.get("remaining_infra_budget_inr") == "8500.00"


def test_infra_scaling_budget_file_override_wins_over_env(monkeypatch):
    """Operator console persists cap under var/; it overrides THIRAMAI_OPERATIONAL_INFRA_BUDGET_INR."""
    import services.economics_service as econ
    from services.dashboard_ops_state import (
        clear_operational_infra_budget_inr_override,
        set_operational_infra_budget_inr_override,
    )

    monkeypatch.setenv("THIRAMAI_OPERATIONAL_INFRA_BUDGET_INR", "99999")
    monkeypatch.setenv("THIRAMAI_WORKER_MONTHLY_COST_INR_EST", "500")
    set_operational_infra_budget_inr_override("2000")
    try:
        out = econ.infra_scaling_budget_check(1, current_worker_nodes=1)
        assert out.get("budget_configured") is True
        assert out.get("budget_cap_inr") == "2000.00"
    finally:
        clear_operational_infra_budget_inr_override()
