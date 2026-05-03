"""
Central typed configuration for THIRAMAI_* (and related) environment variables.

Uses Pydantic Settings for validation. ``load_dotenv`` should run before first access
(see ``app.py``). Modules that still use ``os.getenv`` can migrate incrementally; unknown
env keys remain available via ``os.environ`` for keys not listed here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from pydantic import AliasChoices, Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parent.parent


def _parse_thiramai_trusted_proxy_ips(raw: str) -> list[str]:
    """
    Normalize THIRAMAI_TRUSTED_PROXY_IPS / TRUSTED_PROXY_IPS.

    pydantic-settings JSON-decodes env values for ``list[str]`` *before* field validators,
    so ``""`` raises JSONDecodeError and comma-separated CIDRs fail. We keep the env value
    as a string field and parse here: empty -> [], JSON array, or comma-separated list.
    """
    s = (raw or "").strip()
    if not s:
        return []
    if s.startswith("["):
        try:
            parsed = json.loads(s)
        except json.JSONDecodeError as e:
            raise ValueError(
                "THIRAMAI_TRUSTED_PROXY_IPS / TRUSTED_PROXY_IPS must be valid JSON array "
                f'(e.g. [] or ["127.0.0.1"]) or comma-separated CIDRs. Got {raw!r}'
            ) from e
        if not isinstance(parsed, list):
            raise ValueError(
                "THIRAMAI_TRUSTED_PROXY_IPS must be a JSON array "
                f"of strings, got {type(parsed).__name__}"
            )
        return [str(x).strip() for x in parsed if str(x).strip()]
    return [part.strip() for part in s.split(",") if part.strip()]


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
    # Keep as str so pydantic-settings does not json.loads("") / comma CIDRs before validation.
    trusted_proxy_ips_raw: str = Field(
        default="",
        validation_alias=AliasChoices("THIRAMAI_TRUSTED_PROXY_IPS", "TRUSTED_PROXY_IPS"),
        exclude=True,
        repr=False,
    )
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

    # --- /health/ready tuning (optional; see docs/deployment/HEALTH_CHECKS.md) ---
    THIRAMAI_EXPECTED_DB_REVISION: str = ""
    THIRAMAI_HEALTH_REQUIRE_AI: str = ""
    THIRAMAI_HEALTH_REQUIRE_POLICY_ENGINE: str = ""
    THIRAMAI_HEALTH_STRICT_MODE: str = ""
    THIRAMAI_HEALTH_IGNORE_ALEMBIC_MISMATCH: str = ""
    THIRAMAI_HEALTH_REQUIRE_GOAL_SQLITE: str = ""

    # --- SQLAlchemy connection pool (PostgreSQL / non-SQLite engines) ---
    POOL_SIZE: int = Field(
        default=20,
        ge=1,
        le=500,
        validation_alias=AliasChoices("POOL_SIZE", "THIRAMAI_DB_POOL_SIZE"),
    )
    MAX_OVERFLOW: int = Field(
        default=40,
        ge=0,
        le=500,
        validation_alias=AliasChoices("MAX_OVERFLOW", "THIRAMAI_DB_MAX_OVERFLOW"),
    )
    POOL_TIMEOUT: int = Field(
        default=30,
        ge=5,
        le=300,
        validation_alias=AliasChoices("POOL_TIMEOUT", "THIRAMAI_DB_POOL_TIMEOUT"),
    )
    POOL_RECYCLE: int = Field(
        default=3600,
        ge=60,
        le=86400,
        validation_alias=AliasChoices("POOL_RECYCLE", "THIRAMAI_DB_POOL_RECYCLE"),
    )
    POOL_PRE_PING: bool = Field(
        default=True,
        validation_alias=AliasChoices("POOL_PRE_PING", "THIRAMAI_DB_POOL_PRE_PING"),
    )
    WARN_ON_POOL_CHECKOUT_SECONDS: float = Field(
        default=5.0,
        ge=0.5,
        le=300.0,
        validation_alias=AliasChoices(
            "WARN_ON_POOL_CHECKOUT_SECONDS",
            "THIRAMAI_WARN_ON_POOL_CHECKOUT_SECONDS",
            "THIRAMAI_WARN_SLOW_DB_SECONDS",
        ),
    )
    DB_CONNECT_TIMEOUT_SECONDS: int = Field(
        default=10,
        ge=2,
        le=120,
        validation_alias=AliasChoices(
            "DB_CONNECT_TIMEOUT_SECONDS",
            "THIRAMAI_DB_CONNECT_TIMEOUT_SECONDS",
        ),
    )
    DB_STATEMENT_TIMEOUT_MS: int = Field(
        default=30_000,
        ge=1000,
        le=600_000,
        validation_alias=AliasChoices(
            "DB_STATEMENT_TIMEOUT_MS",
            "THIRAMAI_DB_STATEMENT_TIMEOUT_MS",
        ),
    )

    SECRETS_BACKEND: str = Field(
        default="environment",
        description="Secrets storage backend: environment, aws, vault, gcp",
        validation_alias=AliasChoices("SECRETS_BACKEND", "THIRAMAI_SECRETS_BACKEND"),
    )

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
        "THIRAMAI_EXPECTED_DB_REVISION",
        "THIRAMAI_HEALTH_REQUIRE_AI",
        "THIRAMAI_HEALTH_REQUIRE_POLICY_ENGINE",
        "THIRAMAI_HEALTH_STRICT_MODE",
        "THIRAMAI_HEALTH_IGNORE_ALEMBIC_MISMATCH",
        "THIRAMAI_HEALTH_REQUIRE_GOAL_SQLITE",
        "SECRETS_BACKEND",
        "trusted_proxy_ips_raw",
        mode="before",
    )
    @classmethod
    def _strip_str(cls, v: object) -> str:
        if v is None:
            return ""
        return str(v).strip()

    @field_validator("trusted_proxy_ips_raw", mode="after")
    @classmethod
    def _trusted_proxy_ips_raw_valid(cls, v: str) -> str:
        _parse_thiramai_trusted_proxy_ips(v)
        return v

    @computed_field
    @property
    def trusted_proxy_ips(self) -> list[str]:
        return _parse_thiramai_trusted_proxy_ips(self.trusted_proxy_ips_raw)

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

    def get_secret_or_env(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Resolve *key* via :mod:`core.secrets_manager` first, then ``os.environ``.

        Enables gradual migration: remote backends override local env when configured.
        """
        from core.secrets_manager import get_secret as sm_get

        v = sm_get(key, use_cache=True)
        if v is not None and str(v).strip() != "":
            return str(v).strip()
        fallback = os.getenv(key, default)
        return (fallback.strip() if isinstance(fallback, str) and fallback.strip() else None)

    def get_database_url_secure(self) -> Optional[str]:
        """Prefer ``DATABASE_URL`` from the active secrets backend, then plain env."""
        return self.get_secret_or_env("DATABASE_URL")

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
        - Comma-separated ``THIRAMAI_CORS_ORIGINS`` when set lists allowed origins (``*`` rejected).
        - When unset or ``*``, defaults to ``https://app.thiramai.co.in`` and ``https://thiramai.co.in``.

        Non-production: **never** returns ``*`` (browsers + CORSMiddleware treat wildcard as allow-all).
        ``THIRAMAI_CORS_ALLOW_ALL`` is deprecated: use explicit localhost defaults or ``THIRAMAI_CORS_ORIGINS``.
        """
        if self.is_production():
            raw = (self.THIRAMAI_CORS_ORIGINS or "").strip()
            if not raw or raw == "*":
                return [
                    "https://app.thiramai.co.in",
                    "https://thiramai.co.in",
                ]
            origins = [o.strip() for o in raw.split(",") if o.strip() and o.strip() != "*"]
            if not origins:
                return [
                    "https://app.thiramai.co.in",
                    "https://thiramai.co.in",
                ]
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
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:8000",
        ]


def get_settings() -> ThiramaiSettings:
    """Load settings from environment and optional ``.env`` (new instance; tests may patch ``os.environ``)."""
    return ThiramaiSettings()


def reset_settings_cache() -> None:
    """Tests: clear cache after mutating environment."""
    cc = getattr(get_settings, "cache_clear", None)
    if callable(cc):
        cc()
