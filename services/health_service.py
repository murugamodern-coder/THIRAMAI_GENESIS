"""Deep health checks aggregated for the ``/health/deep`` endpoint.

Each individual checker is **synchronous and best-effort** — it returns a
status string (``"ok"`` / ``"degraded"`` / ``"down"``) plus an optional
short detail message. Nothing here raises: a failed checker degrades the
overall verdict but never blocks the response.

The endpoint is intentionally separate from ``/health/command-center-index``
in :mod:`app` (which is UI-bundle-specific) and from the operator-facing
``/auto-deploy/trigger`` health-check (which gates auto-deploy).
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


_OK = "ok"
_DEGRADED = "degraded"
_DOWN = "down"


# ---------------------------------------------------------------------------
# Individual checkers
# ---------------------------------------------------------------------------


def _check_database() -> tuple[str, str]:
    try:
        from core.database import get_session_factory

        factory = get_session_factory()
    except Exception as exc:
        return _DOWN, f"factory_unavailable: {exc.__class__.__name__}"
    if factory is None:
        return _DOWN, "session_factory_none"
    try:
        from sqlalchemy import text

        with factory() as session:
            session.execute(text("SELECT 1"))
        return _OK, "select_1_ok"
    except Exception as exc:
        return _DOWN, f"query_failed: {exc.__class__.__name__}"


def _check_redis() -> tuple[str, str]:
    try:
        from services.worker_heartbeat import redis_client

        client = redis_client()
    except Exception as exc:
        return _DEGRADED, f"client_unavailable: {exc.__class__.__name__}"
    if client is None:
        return _DEGRADED, "redis_client_none"
    try:
        # ping returns True for healthy redis
        if client.ping():
            return _OK, "ping_ok"
        return _DEGRADED, "ping_returned_false"
    except Exception as exc:
        return _DOWN, f"ping_failed: {exc.__class__.__name__}"


def _check_policy_engine() -> tuple[str, str]:
    try:
        from services.policy_engine import get_policy_engine

        engine = get_policy_engine()
    except Exception as exc:
        return _DEGRADED, f"engine_import_failed: {exc.__class__.__name__}"
    try:
        snapshot = engine.state_snapshot()
    except Exception as exc:
        return _DEGRADED, f"snapshot_failed: {exc.__class__.__name__}"
    actions = snapshot.get("actions") if isinstance(snapshot, dict) else None
    if not actions:
        return _DEGRADED, "no_actions_registered"
    return _OK, f"actions={len(actions)}"


def _check_bandit_persistence() -> tuple[str, str]:
    try:
        from services.policy_engine_persistence import get_persistence

        persistence = get_persistence()
    except Exception as exc:
        return _DEGRADED, f"persistence_import_failed: {exc.__class__.__name__}"
    storage_dir = getattr(persistence, "storage_dir", None) or getattr(
        persistence, "_storage_dir", None
    )
    if storage_dir is None:
        return _DEGRADED, "storage_dir_unknown"
    try:
        from pathlib import Path as _Path

        path = _Path(str(storage_dir))
        if not path.exists():
            return _DEGRADED, "storage_dir_missing"
        return _OK, f"storage={path.name}"
    except Exception as exc:
        return _DEGRADED, f"storage_check_failed: {exc.__class__.__name__}"


def _check_broker() -> tuple[str, str]:
    """Check that broker auth env is present, do NOT make a live API call.

    A live call here would slow ``/health/deep`` and rate-limit the broker.
    This checker only verifies that the configured broker has credentials.
    """
    broker = (os.getenv("THIRAMAI_BROKER") or os.getenv("BROKER") or "paper").strip().lower()
    if broker == "paper":
        return _OK, "paper_broker"
    if broker == "zerodha":
        if (os.getenv("ZERODHA_API_KEY") or "").strip() and (
            os.getenv("ZERODHA_ACCESS_TOKEN") or ""
        ).strip():
            return _OK, "zerodha_creds_present"
        return _DEGRADED, "zerodha_creds_missing"
    if broker == "fyers":
        if (os.getenv("FYERS_APP_ID") or "").strip() and (
            os.getenv("FYERS_ACCESS_TOKEN") or ""
        ).strip():
            return _OK, "fyers_creds_present"
        return _DEGRADED, "fyers_creds_missing"
    return _OK, f"broker={broker}"


def _check_world_model() -> tuple[str, str]:
    try:
        from services.world_model.bayesian_world_model import STATE_VARIABLES

        return _OK, f"variables={len(STATE_VARIABLES)}"
    except Exception as exc:
        return _DEGRADED, f"world_model_import_failed: {exc.__class__.__name__}"


def _check_disk() -> tuple[str, str]:
    """Best-effort free-space check on the repo root partition."""
    try:
        import shutil
        from pathlib import Path

        usage = shutil.disk_usage(str(Path(__file__).resolve().parents[1]))
        free_pct = usage.free / max(usage.total, 1)
        if free_pct < 0.05:
            return _DOWN, f"free={free_pct:.1%}"
        if free_pct < 0.15:
            return _DEGRADED, f"free={free_pct:.1%}"
        return _OK, f"free={free_pct:.1%}"
    except Exception as exc:  # pragma: no cover - defensive
        return _DEGRADED, f"disk_check_failed: {exc.__class__.__name__}"


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


_CHECKERS: tuple[tuple[str, Any], ...] = (
    ("database", _check_database),
    ("redis", _check_redis),
    ("policy_engine", _check_policy_engine),
    ("bandit_persistence", _check_bandit_persistence),
    ("broker", _check_broker),
    ("world_model", _check_world_model),
    ("disk", _check_disk),
)


def run_deep_health_check() -> dict[str, Any]:
    """Run every checker and return a JSON-safe payload.

    Returns the same shape regardless of underlying failures:

        {
          "status": "healthy" | "degraded" | "unhealthy",
          "checks": {"database": {"status": "ok", "detail": "..."}, ...},
          "elapsed_ms": 12.3,
          "timestamp": "...",
        }
    """
    start = time.perf_counter()
    checks: dict[str, dict[str, str]] = {}

    for name, fn in _CHECKERS:
        try:
            status, detail = fn()
        except Exception as exc:  # pragma: no cover - defensive
            status, detail = _DOWN, f"checker_raised: {exc.__class__.__name__}"
        checks[name] = {"status": status, "detail": detail}

    statuses = {c["status"] for c in checks.values()}
    if _DOWN in statuses:
        overall = "unhealthy"
    elif _DEGRADED in statuses:
        overall = "degraded"
    else:
        overall = "healthy"

    elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
    return {
        "status": overall,
        "checks": checks,
        "elapsed_ms": elapsed_ms,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


__all__ = ["run_deep_health_check"]
