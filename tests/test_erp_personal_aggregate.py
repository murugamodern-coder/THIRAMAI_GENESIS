"""Smoke tests for Personal OS aggregate (no DB required for anonymous path)."""

from __future__ import annotations

from services.personal_os_aggregate import build_personal_today_sync


def test_personal_today_anonymous_safe() -> None:
    out = build_personal_today_sync(user_id=0, organization_id=0)
    assert out.get("ok") is True
    assert out["tasks"] == []
    assert out["reminders"] == []
    assert out["experiences"] == []
