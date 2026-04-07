"""Hard stops for unsafe production configurations."""

from __future__ import annotations

import os

from core.settings import get_settings


def is_production_environment() -> bool:
    """True when ``ENV`` or ``THIRAMAI_ENV`` (case-insensitive) is ``production``."""
    return get_settings().is_production()


def assert_safe_production_config() -> None:
    """
    Abort startup when ``ENV`` or ``THIRAMAI_ENV`` is ``production`` and unsafe flags are set.

    - ``THIRAMAI_AUTH_DISABLED`` (any truthy) is rejected.
    - ``THIRAMAI_SAFE_ERRORS`` must be enabled (truthy) so HTTP bodies do not leak internals.
    - ``THIRAMAI_CORS_ORIGINS`` must list explicit origins (validated via ``cors_allow_origins_list()``).

    Raises:
        RuntimeError: Misconfiguration that must never ship.
    """
    if not is_production_environment():
        return
    settings = get_settings()
    raw = (os.getenv("THIRAMAI_AUTH_DISABLED") or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        raise RuntimeError(
            "Refusing to start: THIRAMAI_AUTH_DISABLED is enabled (truthy) while ENV/THIRAMAI_ENV is production."
        )
    if not settings.safe_errors_truthy():
        raise RuntimeError(
            "Refusing to start: set THIRAMAI_SAFE_ERRORS=1 (or true/yes/on) when ENV/THIRAMAI_ENV is production."
        )
    _ = settings.cors_allow_origins_list()
