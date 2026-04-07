"""Run automation with DB-backed idempotency + optional DB job queue scheduling."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from core.observability import LatencyTimer, log_action_engine, new_request_id

from workers import idempotency as idem

T = TypeVar("T")


def run_with_idempotency(
    fn: Callable[[], T],
    *,
    idempotency_key: str,
    action_type: str,
    risk_tier: str,
    request_id: str | None = None,
) -> tuple[bool, T | None, str]:
    """
    If ``idempotency_key`` is already completed (or held in-flight), skip ``fn`` and return
    ``(False, None, 'duplicate')``. Otherwise run ``fn()``, persist completion in DB on success.
    """
    rid = request_id or new_request_id()
    timer = LatencyTimer()

    decision = idem.try_claim_idempotency_slot(idempotency_key, action_type)
    if decision == "duplicate":
        log_action_engine(
            rid,
            "action_engine.duplicate_skipped",
            action_type=action_type,
            idempotency_key=idempotency_key,
            risk_tier=risk_tier,
            ok=True,
            extra={"note": "idempotent_skip"},
        )
        return False, None, "duplicate"

    try:
        out = fn()
    except Exception as exc:
        idem.release_idempotency_claim(idempotency_key)
        log_action_engine(
            rid,
            "action_engine.failed",
            action_type=action_type,
            idempotency_key=idempotency_key,
            risk_tier=risk_tier,
            ok=False,
            error=str(exc),
            extra={"latency_ms": timer.ms()},
        )
        raise

    idem.mark_idempotency_completed(
        idempotency_key,
        action_type=action_type,
        meta={"risk_tier": risk_tier},
    )
    log_action_engine(
        rid,
        "action_engine.completed",
        action_type=action_type,
        idempotency_key=idempotency_key,
        risk_tier=risk_tier,
        ok=True,
        extra={"latency_ms": timer.ms()},
    )
    return True, out, ""


def schedule_task(
    background_add_task: Callable[..., None],
    fn: Callable[..., Any],
    *args: Any,
    idempotency_key: str,
    action_type: str,
    risk_tier: str,
    request_id: str | None = None,
    **kwargs: Any,
) -> str:
    """
    Queue ``fn`` after HTTP response (FastAPI ``BackgroundTasks``).
    Idempotency is enforced inside the worker via ``run_with_idempotency``.
    """

    rid = request_id or new_request_id()

    def _wrapper() -> None:
        def _inner() -> None:
            fn(*args, **kwargs)

        run_with_idempotency(
            _inner,
            idempotency_key=idempotency_key,
            action_type=action_type,
            risk_tier=risk_tier,
            request_id=rid,
        )

    background_add_task(_wrapper)
    log_action_engine(
        rid,
        "action_engine.scheduled",
        action_type=action_type,
        idempotency_key=idempotency_key,
        risk_tier=risk_tier,
        ok=True,
    )
    return rid
