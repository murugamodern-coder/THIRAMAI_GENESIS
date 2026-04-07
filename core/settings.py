"""
Central typed configuration for THIRAMAI_* (and related) environment variables.

Uses Pydantic Settings for validation. ``load_dotenv`` should run before first access
(see ``app.py``). Modules that still use ``os.getenv`` can migrate incrementally; unknown
env keys remain available via ``os.environ`` for keys not listed here.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parent.parent


def _truthy(raw: str) -> bool:
    return raw.strip().lower() in ("1", "true", "yes", "on")


class ThiramaiSettings(BaseSettings):
    """Validated environment-backed settings (THIRAMAI_* and core deployment flags)."""

    model_config = SettingsConfigDict(
        env_file=_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Core environment ---
    ENV: str = ""
    THIRAMAI_ENV: str = ""

    # --- CORS ---
    THIRAMAI_CORS_ALLOW_ALL: str = ""
    THIRAMAI_CORS_ORIGINS: str = ""

    # --- HTTP error masking ---
    THIRAMAI_SAFE_ERRORS: str = ""

    # --- Schedulers / agents (typed for app.py) ---
    THIRAMAI_ENABLE_ALERT_SCHEDULER: str = ""
    THIRAMAI_SOVEREIGN_SCHEDULER: str = ""
    THIRAMAI_BACKGROUND_AGENT: str = ""

    # --- Server (optional; main/run use os.getenv still) ---
    THIRAMAI_HOST: str = ""
    THIRAMAI_PORT: str = ""
    THIRAMAI_UVICORN_RELOAD: str = ""

    # --- Common THIRAMAI_* (validated strings; use helpers where needed) ---
    THIRAMAI_AUTH_DISABLED: str = ""
    THIRAMAI_DASHBOARD_WS_INTERVAL: str = ""
    THIRAMAI_DASHBOARD_LOW_STOCK_THRESHOLD: str = ""
    THIRAMAI_RL_TRUST_X_FORWARDED_FOR: str = ""
    THIRAMAI_STRICT_ORIGIN: str = ""

    @field_validator(
        "THIRAMAI_CORS_ALLOW_ALL",
        "THIRAMAI_SAFE_ERRORS",
        "THIRAMAI_ENABLE_ALERT_SCHEDULER",
        "THIRAMAI_SOVEREIGN_SCHEDULER",
        "THIRAMAI_BACKGROUND_AGENT",
        mode="before",
    )
    @classmethod
    def _strip_str(cls, v: object) -> str:
        if v is None:
            return ""
        return str(v).strip()

    def is_production(self) -> bool:
        return (self.ENV or self.THIRAMAI_ENV or "").strip().lower() == "production"

    def cors_allow_all_truthy(self) -> bool:
        return _truthy(self.THIRAMAI_CORS_ALLOW_ALL)

    def safe_errors_truthy(self) -> bool:
        return _truthy(self.THIRAMAI_SAFE_ERRORS)

    def scheduler_alert_truthy(self) -> bool:
        return _truthy(self.THIRAMAI_ENABLE_ALERT_SCHEDULER)

    def scheduler_sovereign_truthy(self) -> bool:
        return _truthy(self.THIRAMAI_SOVEREIGN_SCHEDULER)

    def background_agent_truthy(self) -> bool:
        return _truthy(self.THIRAMAI_BACKGROUND_AGENT)

    def disable_openapi_uis(self) -> bool:
        """Hide Swagger UI and Redoc in production."""
        return self.is_production()

    def cors_allow_origins_list(self) -> list[str]:
        """
        Origins for CORSMiddleware.

        In **production** (``ENV`` or ``THIRAMAI_ENV`` = ``production``):
        - ``THIRAMAI_CORS_ALLOW_ALL`` is **ignored** (never ``*``).
        - Only explicit comma-separated ``THIRAMAI_CORS_ORIGINS`` values are allowed
          (must be non-empty; ``*`` is rejected).

        Non-production: **never** returns ``*`` (browsers + CORSMiddleware treat wildcard as allow-all).
        ``THIRAMAI_CORS_ALLOW_ALL`` is deprecated: use explicit localhost defaults or ``THIRAMAI_CORS_ORIGINS``.
        """
        if self.is_production():
            raw = (self.THIRAMAI_CORS_ORIGINS or "").strip()
            if not raw or raw == "*":
                raise RuntimeError(
                    "Production requires non-empty THIRAMAI_CORS_ORIGINS with explicit origins "
                    "(comma-separated). Wildcard * is not allowed."
                )
            origins = [o.strip() for o in raw.split(",") if o.strip() and o.strip() != "*"]
            if not origins:
                raise RuntimeError(
                    "Production THIRAMAI_CORS_ORIGINS must list at least one explicit origin (no *)."
                )
            return origins

        # Dev / staging: explicit origins only (no "*" — Starlette allow_origins=["*"] is insecure for creds + ambiguous).
        raw = (self.THIRAMAI_CORS_ORIGINS or "").strip()
        if raw and raw != "*":
            origins = [o.strip() for o in raw.split(",") if o.strip() and o.strip() != "*"]
            if origins:
                return origins
        if self.cors_allow_all_truthy():
            # Legacy: treat "allow all" as the same explicit dev list (log once via app startup if needed).
            pass
        return [
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            # Vite dev server (Command Center SPA)
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]


def get_settings() -> ThiramaiSettings:
    """Load settings from environment and optional ``.env`` (new instance; tests may patch ``os.environ``)."""
    return ThiramaiSettings()


def reset_settings_cache() -> None:
    """Tests: clear cache after mutating environment."""
    get_settings.cache_clear()
