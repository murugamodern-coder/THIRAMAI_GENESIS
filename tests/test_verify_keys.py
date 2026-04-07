"""Unit tests for external API / schema helpers in ``services.verify_keys``."""

from __future__ import annotations

from unittest.mock import patch

from services.verify_keys import extract_missing_column_from_error


def test_extract_missing_column_postgres_quoted() -> None:
    msg = 'column "gst_number" of relation "organizations" does not exist'
    assert extract_missing_column_from_error(msg) == "gst_number"


def test_extract_missing_column_sqlite() -> None:
    msg = "sqlite3.OperationalError: no such column: foo_bar"
    assert extract_missing_column_from_error(msg) == "foo_bar"


def test_sre_report_includes_external_connectivity_and_schema() -> None:
    from services.sre_health_report import build_sre_health_report

    with (
        patch("services.verify_keys.external_connectivity_report") as m_ext,
        patch("services.verify_keys.external_api_heartbeat_report") as m_hb,
        patch("services.verify_keys.probe_database_schema") as m_probe,
    ):
        m_ext.return_value = {"ok": True, "detail": "mock", "services": {}, "failures": [], "profile": "development"}
        m_hb.return_value = {
            "ok": True,
            "detail": "mock",
            "groq": {},
            "tavily": {},
            "digitalocean": {},
            "profile": "development",
        }
        m_probe.return_value = {"ok": True, "skipped": True, "detail": "mock", "missing_column": None, "error_full": None}
        r = build_sre_health_report(profile="development", write_reflection=False)
    assert "external_connectivity" in r.get("checks", {})
    assert "database_schema" in r.get("checks", {})
    assert "external_api_heartbeat" in r.get("checks", {})
    assert r["checks"]["external_connectivity"]["ok"] is True
