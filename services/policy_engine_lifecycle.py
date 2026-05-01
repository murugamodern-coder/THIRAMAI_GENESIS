"""
FastAPI lifecycle integration for :class:`PolicyEngine` persistence.

This module is **opt-in** — ``app.py`` is not modified by default. To enable
persistence and Prometheus mirroring, add a single line near the bottom of
``app.py`` (after the existing ``app = FastAPI(...)`` definition)::

    from services.policy_engine_lifecycle import register_policy_engine_lifecycle
    register_policy_engine_lifecycle(app)

This adds two ``@app.on_event`` handlers that:

1. on **startup** — load persisted bandit weights from disk and install the
   auto-save hook;
2. on **shutdown** — flush a final checkpoint so in-flight learning is not
   lost.

The handlers are fault-tolerant: any exception is logged and swallowed so a
broken state file cannot prevent the API from booting.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from services.observability.decision_metrics import track_bandit_state
from services.policy_engine import get_policy_engine
from services.policy_engine_persistence import (
    get_persistence,
    init_policy_engine_with_persistence,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


def _is_truthy_env(name: str, *, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def register_policy_engine_lifecycle(app: "FastAPI") -> None:
    """Attach PolicyEngine startup / shutdown handlers to ``app``.

    Disabled by default outside production-style deployments. Set
    ``THIRAMAI_POLICY_PERSISTENCE=1`` to force-enable, or ``=0`` to force-skip.
    """

    enabled = _is_truthy_env("THIRAMAI_POLICY_PERSISTENCE", default=True)
    if not enabled:
        logger.info("PolicyEngine persistence disabled by env flag")
        return

    every_n = 100
    raw_n = (os.getenv("THIRAMAI_POLICY_AUTOSAVE_EVERY") or "").strip()
    if raw_n:
        try:
            every_n = max(1, int(raw_n))
        except ValueError:
            logger.warning(
                "Invalid THIRAMAI_POLICY_AUTOSAVE_EVERY=%r — using default %d",
                raw_n,
                every_n,
            )

    @app.on_event("startup")
    def _policy_engine_startup() -> None:  # pragma: no cover - exercised by app boot
        try:
            engine = init_policy_engine_with_persistence(
                every_n_decisions=every_n
            )
            track_bandit_state(engine.bandit.actions)
            logger.info(
                "PolicyEngine persistence initialized (autosave every %d decisions)",
                every_n,
            )
        except Exception as exc:
            logger.warning("PolicyEngine persistence init failed: %s", exc, exc_info=True)

    @app.on_event("shutdown")
    def _policy_engine_shutdown() -> None:  # pragma: no cover - exercised by app boot
        try:
            persistence = get_persistence()
            engine = get_policy_engine()
            persistence.save_state(engine)
            logger.info("PolicyEngine final checkpoint saved on shutdown")
        except Exception as exc:
            logger.warning("PolicyEngine shutdown checkpoint failed: %s", exc, exc_info=True)


__all__ = ["register_policy_engine_lifecycle"]
