"""Pytest defaults: non-production app startup + detailed HTTP error bodies."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _tests_use_verbose_api_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("THIRAMAI_ENV", "development")
    monkeypatch.setenv("THIRAMAI_SAFE_ERRORS", "0")
