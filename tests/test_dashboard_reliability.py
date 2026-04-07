"""Reliability: live dashboard always receives ``corporate_identity`` (empty org / DB failures)."""

from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.dashboard import router as dashboard_router
from services.dashboard_live_context import (
    assert_corporate_identity_template_integrity,
    safe_corporate_identity_for_live_dashboard,
)
from services.sre_health_report import build_sre_health_report


def _dashboard_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(dashboard_router)
    return app


def test_safe_corporate_identity_fallback_when_economics_raises(monkeypatch) -> None:
    monkeypatch.setenv("THIRAMAI_CORPORATE_DASHBOARD_ORG_ID", "1")

    def _boom(_oid: int) -> dict:
        raise RuntimeError("simulated_db_failure")

    with patch("services.economics_service.get_corporate_economics_context", _boom):
        snap = safe_corporate_identity_for_live_dashboard()
    assert snap["company_name"] == "Modern Corporation"
    assert snap["gst_number"] == "33BTHPM0629L3ZJ"
    assert snap["organization_id"] == 1
    ok, _ = assert_corporate_identity_template_integrity(snap)
    assert ok


def test_safe_corporate_identity_when_org_row_missing(monkeypatch) -> None:
    """Simulates empty/missing organization row: economics returns empty strings, shape stays valid."""
    monkeypatch.setenv("THIRAMAI_CORPORATE_DASHBOARD_ORG_ID", "999")

    def _empty(_oid: int) -> dict:
        return {"organization_id": 999, "company_name": "", "gst_number": None}

    with patch("services.economics_service.get_corporate_economics_context", _empty):
        snap = safe_corporate_identity_for_live_dashboard()
    assert snap["organization_id"] == 999
    assert snap["company_name"] == ""
    assert snap["name"] == ""
    assert snap["gst_number"] is None
    ok, detail = assert_corporate_identity_template_integrity(snap)
    assert ok, detail


def test_dashboard_live_renders_when_corporate_context_empty(monkeypatch) -> None:
    def _empty(_oid: int) -> dict:
        return {"organization_id": 1, "company_name": "", "gst_number": None}

    with patch("services.economics_service.get_corporate_economics_context", _empty):
        c = TestClient(_dashboard_test_app())
        r = c.get("/dashboard/live")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    body = r.text
    assert "Executive Cockpit" in body or "THIRAMAI" in body


def test_dashboard_state_json_always_has_corporate_identity_shape() -> None:
    c = TestClient(_dashboard_test_app())
    r = c.get("/dashboard/live/state.json")
    assert r.status_code == 200
    j = r.json()
    ci = j.get("corporate_identity")
    assert isinstance(ci, dict)
    assert "organization_id" in ci
    assert "name" in ci
    assert "company_name" in ci
    assert "gst_number" in ci


def test_sre_monitors_template_variable_integrity() -> None:
    report = build_sre_health_report(profile="development", write_reflection=False)
    chk = report.get("checks", {}).get("dashboard_template_variable_integrity")
    assert chk is not None
    assert chk.get("ok") is True
    assert "detail" in chk


def test_sre_monitors_organization_integrity() -> None:
    report = build_sre_health_report(profile="development", write_reflection=False)
    chk = report.get("checks", {}).get("organization_integrity")
    assert chk is not None
    assert "ok" in chk
    assert "detail" in chk


def test_sre_external_api_keys_check_present() -> None:
    report = build_sre_health_report(profile="development", write_reflection=False)
    ext = report.get("checks", {}).get("external_api_keys")
    assert ext is not None
    assert ext.get("ok") is True
    assert "presence" in ext
    assert "warnings" in ext
    assert "GROQ_API_KEY" in (ext.get("presence") or {})


def test_auto_repair_command_bypasses_groq(monkeypatch) -> None:
    """Run console must invoke self-heal without GROQ_API_KEY when keywords match."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    def _fake_run(**kwargs: object) -> dict:
        return {
            "ok": True,
            "forced": bool(kwargs.get("force")),
            "steps": [{"step": "alembic", "ok": True}],
            "restart": {"ok": False, "step": "restart", "detail": "skipped"},
        }

    with patch("services.auto_repair.run_auto_repair", _fake_run):
        from services.dashboard_command_executor import execute_natural_language_dashboard_command

        out = execute_natural_language_dashboard_command(
            raw_command="auto repair database",
            organization_id=1,
            sre_profile="development",
        )
    assert out.get("ok") is True
    assert out.get("executed") == "run_auto_repair"


def test_assert_corporate_identity_rejects_bad_snap() -> None:
    ok, msg = assert_corporate_identity_template_integrity(None)
    assert ok is False
    ok2, _ = assert_corporate_identity_template_integrity({"organization_id": 1})
    assert ok2 is False
