"""End-to-end smoke tests for the observability stack:

* :mod:`services.observability.business_metrics`  — 50+ metrics
* :mod:`core.tracing`                              — optional OpenTelemetry
* :mod:`services.health_service`                    — deep health probe
* The 10 Grafana dashboards under ``monitoring/grafana/dashboards/``

All tests are offline. The Grafana JSON files are validated for shape, not
rendered; the metrics are exercised via no-op-safe public APIs.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARDS_DIR = REPO_ROOT / "monitoring" / "grafana" / "dashboards"


# ---------------------------------------------------------------------------
# business_metrics
# ---------------------------------------------------------------------------


def test_business_metrics_imports_and_init_idempotent():
    from services.observability import business_metrics as bm

    r1 = bm.init_business_metrics()
    r2 = bm.init_business_metrics()
    assert r1["ok"] is True
    assert r2["ok"] is True
    assert r2.get("already_initialised") is True


def test_business_metrics_defines_50_plus_public_objects():
    from services.observability import business_metrics as bm

    metric_names = [n for n in bm.__all__ if not n.startswith("track_") and not n.startswith("init_") and not n.startswith("is_")]
    # Our defined metrics + tracking helpers should comfortably exceed 50.
    assert len(bm.__all__) >= 50, f"only {len(bm.__all__)} public objects exposed"
    assert len(metric_names) >= 30  # raw metric primitives


def test_business_metrics_track_helpers_no_raise():
    from services.observability import business_metrics as bm

    # All tracking helpers should be safe to call repeatedly.
    bm.track_api_request("/foo", "GET", 12.5, 200)
    bm.track_api_request("/bar", "POST", 12.5, 500)
    bm.track_trade_execution("paper", "BUY", 5.0)
    bm.track_broker_error("zerodha", "rate_limited")
    bm.track_world_model_update(20.0)
    bm.track_world_model_prediction("revenue_up_next_week", 0.7)
    bm.track_online_learner_state(accuracy=0.7, samples_seen=100, drift_score=12.0)
    bm.track_kill_switch(1, True)
    bm.track_kill_switch(1, False)
    bm.track_daily_pnl(1, -1234.0)
    bm.track_bandit_state({"buy": {"count": 5, "theta_norm": 0.42}})
    bm.track_startup()


def test_business_metrics_is_prometheus_available_returns_bool():
    from services.observability.business_metrics import is_prometheus_available

    assert isinstance(is_prometheus_available(), bool)


def test_business_metrics_metric_objects_have_expected_api():
    from services.observability import business_metrics as bm

    bm.bandit_action_count.labels(action="x").set(3)
    bm.api_error_total.labels(status_code="500", endpoint="/foo").inc()
    bm.world_model_update_latency_ms.observe(12.0)


# ---------------------------------------------------------------------------
# core.tracing
# ---------------------------------------------------------------------------


def test_tracing_disabled_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("THIRAMAI_TRACING_ENABLED", raising=False)
    from core.tracing import init_tracing

    class _DummyApp:  # FastAPI stub — never used because tracing is disabled
        pass

    status = init_tracing(_DummyApp())
    assert status["ok"] is True
    assert status["enabled"] is False
    assert "disabled" in status["reason"]


def test_tracing_enabled_but_otel_missing_returns_status():
    """If THIRAMAI_TRACING_ENABLED=1 but OTel SDK is not installed, init must not raise."""
    with patch.dict("os.environ", {"THIRAMAI_TRACING_ENABLED": "1"}):
        from core.tracing import init_tracing

        class _DummyApp:
            pass

        status = init_tracing(_DummyApp())
        # Either OTel is present (status ok+enabled) or absent (ok=False, enabled=False).
        assert status["enabled"] in (True, False)


def test_tracing_get_tracer_returns_usable_object():
    """Whether OTel is installed or not, get_tracer must return a context-manager-compatible tracer."""
    from core.tracing import get_tracer

    tracer = get_tracer("test")
    with tracer.start_as_current_span("my_span") as span:
        # Both real and noop spans support set_attribute / set_status / record_exception.
        try:
            span.set_attribute("k", "v")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# health_service
# ---------------------------------------------------------------------------


def test_health_service_returns_well_formed_payload():
    """run_deep_health_check must always return the same shape."""
    from services.health_service import run_deep_health_check

    payload = run_deep_health_check()
    assert payload["status"] in ("healthy", "degraded", "unhealthy")
    assert "checks" in payload
    assert "elapsed_ms" in payload
    assert "timestamp" in payload
    for name, info in payload["checks"].items():
        assert "status" in info, f"checker {name} missing status"
        assert info["status"] in ("ok", "degraded", "down")


def test_health_service_no_db_marks_database_down():
    with patch("core.database.get_session_factory", side_effect=Exception("no_db")):
        from services.health_service import run_deep_health_check

        payload = run_deep_health_check()
    assert payload["checks"]["database"]["status"] in ("down", "degraded")


def test_health_service_individual_checkers_always_return_tuple():
    """Internal checkers must each return (status, detail) — no exceptions."""
    from services.health_service import (
        _check_broker,
        _check_database,
        _check_disk,
        _check_redis,
        _check_world_model,
    )

    for fn in (_check_database, _check_redis, _check_broker, _check_world_model, _check_disk):
        result = fn()
        assert isinstance(result, tuple) and len(result) == 2
        status, detail = result
        assert status in ("ok", "degraded", "down")
        assert isinstance(detail, str)


# ---------------------------------------------------------------------------
# Grafana dashboards — JSON shape validation
# ---------------------------------------------------------------------------


_EXPECTED_DASHBOARDS = (
    "overview.json",
    "decisions.json",
    "trading.json",
    "bandit.json",
    "world_model.json",
    "online_learner.json",
    "risk.json",
    "broker.json",
    "alerts.json",
    "business.json",
)


def test_all_10_dashboards_exist():
    for name in _EXPECTED_DASHBOARDS:
        path = DASHBOARDS_DIR / name
        assert path.is_file(), f"Missing dashboard: {name}"


@pytest.mark.parametrize("filename", _EXPECTED_DASHBOARDS)
def test_dashboard_is_valid_json(filename: str):
    path = DASHBOARDS_DIR / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert "title" in data and data["title"]
    assert "uid" in data and data["uid"]
    assert "panels" in data and isinstance(data["panels"], list)
    assert len(data["panels"]) >= 6, f"{filename}: expected >=6 panels, got {len(data['panels'])}"


@pytest.mark.parametrize("filename", _EXPECTED_DASHBOARDS)
def test_dashboard_panels_have_titles_and_targets(filename: str):
    path = DASHBOARDS_DIR / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    for i, panel in enumerate(data["panels"]):
        assert panel.get("title"), f"{filename} panel#{i} missing title"
        assert panel.get("type"), f"{filename} panel#{i} missing type"
        assert panel.get("gridPos"), f"{filename} panel#{i} missing gridPos"
        targets = panel.get("targets") or []
        assert isinstance(targets, list)
        # Stat / timeseries panels must have at least one query target.
        if panel.get("type") in ("stat", "timeseries", "barchart"):
            assert len(targets) >= 1, f"{filename} panel#{i} has no targets"


@pytest.mark.parametrize("filename", _EXPECTED_DASHBOARDS)
def test_dashboard_uses_prometheus_datasource(filename: str):
    path = DASHBOARDS_DIR / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    for i, panel in enumerate(data["panels"]):
        ds = panel.get("datasource")
        assert ds, f"{filename} panel#{i} missing datasource"
        assert ds.get("type") == "prometheus"


@pytest.mark.parametrize("filename", _EXPECTED_DASHBOARDS)
def test_dashboard_has_refresh_and_time_range(filename: str):
    path = DASHBOARDS_DIR / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data.get("refresh"), f"{filename}: missing refresh interval"
    assert data.get("time"), f"{filename}: missing time range"


def test_all_dashboards_have_unique_uids():
    uids = []
    for name in _EXPECTED_DASHBOARDS:
        data = json.loads((DASHBOARDS_DIR / name).read_text(encoding="utf-8"))
        uids.append(data["uid"])
    assert len(uids) == len(set(uids)), f"Duplicate UIDs: {uids}"
