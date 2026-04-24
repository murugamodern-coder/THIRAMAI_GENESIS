"""
Central typed configuration for THIRAMAI_* (and related) environment variables.

Uses Pydantic Settings for validation. ``load_dotenv`` should run before first access
(see ``app.py``). Modules that still use ``os.getenv`` can migrate incrementally; unknown
env keys remain available via ``os.environ`` for keys not listed here.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
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
    THIRAMAI_DEBUG: str = ""
    THIRAMAI_ENFORCE_SECURE_COOKIES: str = ""
    THIRAMAI_DISABLE_AUTO_SCHEMA_CREATE: str = ""
    THIRAMAI_DASHBOARD_WS_INTERVAL: str = ""
    THIRAMAI_DASHBOARD_LOW_STOCK_THRESHOLD: str = ""
    THIRAMAI_RL_TRUST_X_FORWARDED_FOR: str = ""
    trusted_proxy_ips: list[str] = Field(default_factory=list, validation_alias="THIRAMAI_TRUSTED_PROXY_IPS")
    THIRAMAI_STRICT_ORIGIN: str = ""
    # Comma-separated Host header allow-list (like Django ALLOWED_HOSTS). Empty = disabled.
    THIRAMAI_ALLOWED_HOSTS: str = ""
    # Incident / degraded startup (``python run_system.py`` may set when checks fail).
    THIRAMAI_INCIDENT_MODE: str = ""
    THIRAMAI_STARTUP_DEGRADED: str = ""
    # Set to 1 to serve legacy ``static/index.html`` at ``GET /`` again (emergency rollback only).
    THIRAMAI_LEGACY_ROOT_SPA: str = ""
    # Optional deploy id (git SHA, image tag). When set, app redirects use
    # ``/static/command_center/index.html?v=<id>#/...`` so browsers/CDNs cannot reuse a cached shell.
    THIRAMAI_COMMAND_CENTER_BUILD_ID: str = ""

    @field_validator(
        "THIRAMAI_CORS_ALLOW_ALL",
        "THIRAMAI_SAFE_ERRORS",
        "THIRAMAI_ENABLE_ALERT_SCHEDULER",
        "THIRAMAI_SOVEREIGN_SCHEDULER",
        "THIRAMAI_BACKGROUND_AGENT",
        "THIRAMAI_LEGACY_ROOT_SPA",
        "THIRAMAI_DEBUG",
        "THIRAMAI_ENFORCE_SECURE_COOKIES",
        "THIRAMAI_DISABLE_AUTO_SCHEMA_CREATE",
        "THIRAMAI_COMMAND_CENTER_BUILD_ID",
        "THIRAMAI_INCIDENT_MODE",
        "THIRAMAI_STARTUP_DEGRADED",
        mode="before",
    )
    @classmethod
    def _strip_str(cls, v: object) -> str:
        if v is None:
            return ""
        return str(v).strip()

    @field_validator("trusted_proxy_ips", mode="before")
    @classmethod
    def parse_proxy_ips(cls, v: object) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [ip.strip() for ip in v.split(",") if ip.strip()]
        if isinstance(v, list):
            return [str(ip).strip() for ip in v if str(ip).strip()]
        return []

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

    def debug_truthy(self) -> bool:
        return _truthy(self.THIRAMAI_DEBUG)

    def enforce_secure_cookies_truthy(self) -> bool:
        return _truthy(self.THIRAMAI_ENFORCE_SECURE_COOKIES)

    def disable_auto_schema_create_truthy(self) -> bool:
        return _truthy(self.THIRAMAI_DISABLE_AUTO_SCHEMA_CREATE)

    def incident_mode_truthy(self) -> bool:
        """Reduce background load when ops or startup validation enables incident / degraded mode."""
        return _truthy(self.THIRAMAI_INCIDENT_MODE) or _truthy(self.THIRAMAI_STARTUP_DEGRADED)

    def legacy_root_spa_truthy(self) -> bool:
        return _truthy(self.THIRAMAI_LEGACY_ROOT_SPA)

    def command_center_shell_url(self, fragment: str, *, hash_query: str | None = None) -> str:
        """
        HashRouter SPA entry: ``/static/command_center/index.html[?v=build]#/fragment[?hash_query]``.

        *fragment* is a route tail such as ``today`` or ``personal/integrations`` (with or without ``/``).
        *hash_query* is appended after the hash path (for OAuth return params on the client route).
        """
        from urllib.parse import quote

        raw = (fragment or "today").strip().lstrip("#").lstrip("/")
        path_part = "/" + raw if raw else "/today"
        path = "/static/command_center/index.html"
        bid = (self.THIRAMAI_COMMAND_CENTER_BUILD_ID or "").strip()
        if bid:
            path = f"{path}?v={quote(bid, safe='')}"
        h = f"#{path_part}"
        if hash_query:
            hq = hash_query.lstrip("?&")
            h += "?" + hq
        return path + h

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
