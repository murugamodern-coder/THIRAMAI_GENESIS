"""Phase 1: RBAC permissions + CORS allow-list (no wildcard)."""

from __future__ import annotations

import pytest

from core.rbac import Permission, permissions_for_role, user_has_permission
from core.settings import ThiramaiSettings


def test_owner_has_hitl_approve() -> None:
    assert user_has_permission(role_name="owner", permission=Permission.HITL_APPROVE.value)


def test_worker_lacks_hitl_approve() -> None:
    assert not user_has_permission(role_name="worker", permission=Permission.HITL_APPROVE.value)


def test_manager_has_billing_invoice_create() -> None:
    assert user_has_permission(role_name="manager", permission=Permission.BILLING_INVOICE_CREATE.value)


def test_cors_never_wildcard_non_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("THIRAMAI_CORS_ALLOW_ALL", "1")
    s = ThiramaiSettings()
    o = s.cors_allow_origins_list()
    assert "*" not in o
    assert "http://localhost:8000" in o


def test_cors_explicit_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("THIRAMAI_CORS_ORIGINS", "http://127.0.0.1:9999")
    s = ThiramaiSettings()
    assert s.cors_allow_origins_list() == ["http://127.0.0.1:9999"]


def test_permissions_for_role_unknown_empty() -> None:
    assert permissions_for_role("unknown_role_xyz") == frozenset()
