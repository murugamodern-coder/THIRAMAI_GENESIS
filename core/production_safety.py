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
    if settings.debug_truthy():
        raise RuntimeError("Refusing to start: THIRAMAI_DEBUG must be disabled in production.")
    if not settings.enforce_secure_cookies_truthy():
        raise RuntimeError("Refusing to start: THIRAMAI_ENFORCE_SECURE_COOKIES must be enabled in production.")
    if not settings.disable_auto_schema_create_truthy():
        raise RuntimeError("Refusing to start: THIRAMAI_DISABLE_AUTO_SCHEMA_CREATE must be enabled in production.")

    try:
        access_minutes = int((os.getenv("JWT_ACCESS_EXPIRE_MINUTES") or os.getenv("JWT_EXPIRE_MINUTES") or "30").strip())
    except ValueError:
        access_minutes = 30
    if access_minutes > 60:
        raise RuntimeError("Refusing to start: JWT access expiry must be <= 60 minutes in production.")
    try:
        refresh_days = int((os.getenv("JWT_REFRESH_EXPIRE_DAYS") or "30").strip())
    except ValueError:
        refresh_days = 30
    if refresh_days <= 0 or refresh_days > 45:
        raise RuntimeError("Refusing to start: JWT refresh expiry must be in range 1..45 days in production.")
