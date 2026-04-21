"""Unit tests for ``core.startup_checks`` (no FastAPI app import)."""

from __future__ import annotations

from pathlib import Path

import pytest


def _write_cc(root: Path, *, bad_ref: bool = False) -> None:
    cc = root / "static" / "command_center"
    cc.mkdir(parents=True)
    (cc / "cc-app-abc123.js").write_text("export {};", encoding="utf-8")
    (cc / "cc-vendor-xyz.js").write_text("export {};", encoding="utf-8")
    extra = "" if bad_ref else '<script type="module" src="/cc-vendor-xyz.js"></script>'
    if bad_ref:
        extra = '<script type="module" src="/cc-missing-chunk.js"></script>'
    html = f"""<!doctype html><html><head></head><body>
<script type="module" crossorigin src="cc-app-abc123.js"></script>
{extra}
</body></html>"""
    (cc / "index.html").write_text(html, encoding="utf-8")


def test_check_bundle_integrity_ok(tmp_path: Path) -> None:
    from core.startup_checks import check_bundle_integrity

    _write_cc(tmp_path)
    r = check_bundle_integrity(root=tmp_path)
    assert r.ok
    assert "entry=cc-app-abc123.js" in r.detail


def test_check_bundle_integrity_missing_chunk(tmp_path: Path) -> None:
    from core.startup_checks import check_bundle_integrity

    _write_cc(tmp_path, bad_ref=True)
    r = check_bundle_integrity(root=tmp_path)
    assert not r.ok
    assert "missing" in r.detail.lower()


def test_check_required_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.startup_checks import check_required_env

    monkeypatch.setenv("THIRAMAI_STARTUP_TEST_KEY", "set")
    assert check_required_env(["THIRAMAI_STARTUP_TEST_KEY"]).ok
    monkeypatch.delenv("THIRAMAI_STARTUP_TEST_KEY", raising=False)
    r = check_required_env(["THIRAMAI_STARTUP_TEST_KEY"])
    assert not r.ok


def test_run_startup_checks_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.startup_checks import run_startup_checks

    _write_cc(tmp_path)
    monkeypatch.setenv("THIRAMAI_STARTUP_REQUIRED_ENV", "")
    rep = run_startup_checks(root=tmp_path, probe_api_base=None, required_env=[])
    assert rep.ok
    assert not rep.degraded_recommended


def test_settings_incident_disables_scheduler_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THIRAMAI_ENABLE_ALERT_SCHEDULER", "1")
    monkeypatch.setenv("THIRAMAI_INCIDENT_MODE", "1")
    from core import settings as settings_mod

    if hasattr(settings_mod.get_settings, "cache_clear"):
        settings_mod.get_settings.cache_clear()
    s = settings_mod.ThiramaiSettings()
    assert s.incident_mode_truthy() is True
    assert s.scheduler_alert_truthy() is True
