"""Structured logging: request id, latency, approximate token cost, action engine."""

from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid
from typing import Any

_log = logging.getLogger("thiramai")

_trace_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("thiramai_trace_id", default=None)
_org_id_ctx: contextvars.ContextVar[int | None] = contextvars.ContextVar("thiramai_org_id", default=None)


def set_log_context(
    *,
    trace_id: str | None = None,
    organization_id: int | None = None,
) -> None:
    """Bind ``trace_id`` and ``organization_id`` for the current async/task context."""
    if trace_id is not None:
        _trace_id_ctx.set(trace_id)
    if organization_id is not None:
        _org_id_ctx.set(organization_id)


def clear_log_context() -> None:
    _trace_id_ctx.set(None)
    _org_id_ctx.set(None)


def log_structured(event: str, **fields: Any) -> None:
    """Single JSON log line with optional ``trace_id`` / ``organization_id`` from context."""
    payload: dict[str, Any] = {"event": event}
    tid = _trace_id_ctx.get()
    if tid:
        payload["trace_id"] = tid
    oid = _org_id_ctx.get()
    if oid is not None:
        payload["organization_id"] = oid
    for k, v in fields.items():
        if v is not None:
            payload[k] = v
    _log.info(json.dumps(payload, ensure_ascii=False, default=str))


def new_request_id() -> str:
    return str(uuid.uuid4())


def log_event(
    request_id: str,
    event: str,
    *,
    latency_ms: float | None = None,
    tool: str | None = None,
    ok: bool | None = None,
    token_prompt_est: int | None = None,
    token_completion: int | None = None,
    token_cost_units: float | None = None,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "request_id": request_id,
        "event": event,
    }
    tid = _trace_id_ctx.get()
    payload["trace_id"] = tid if tid else request_id
    oid_ctx = _org_id_ctx.get()
    if oid_ctx is not None:
        payload["organization_id"] = oid_ctx
    if latency_ms is not None:
        payload["latency_ms"] = round(latency_ms, 2)
    if tool:
        payload["tool"] = tool
    if ok is not None:
        payload["ok"] = ok
    if token_prompt_est is not None:
        payload["token_prompt_est"] = token_prompt_est
    if token_completion is not None:
        payload["token_completion"] = token_completion
    if token_cost_units is not None:
        payload["token_cost_units"] = round(token_cost_units, 6)
    if error:
        payload["error"] = error[:2000]
    if extra:
        payload.update(extra)
    _log.info(json.dumps(payload, ensure_ascii=False, default=str))


def log_action_engine(
    request_id: str,
    event: str,
    *,
    action_type: str | None = None,
    idempotency_key: str | None = None,
    risk_tier: str | None = None,
    ok: bool | None = None,
    error: str | None = None,
    retry_count: int | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Sovereign Action Engine — success/failure/duplicate for automation audit trail."""
    payload: dict[str, Any] = {
        "request_id": request_id,
        "event": event,
        "channel": "action_engine",
    }
    tid = _trace_id_ctx.get()
    payload["trace_id"] = tid if tid else request_id
    oid_ctx = _org_id_ctx.get()
    if oid_ctx is not None:
        payload["organization_id"] = oid_ctx
    if action_type:
        payload["action_type"] = action_type
    if idempotency_key:
        payload["idempotency_key"] = idempotency_key
    if risk_tier:
        payload["risk_tier"] = risk_tier
    if ok is not None:
        payload["ok"] = ok
    if error:
        payload["error"] = error[:2000]
    if retry_count is not None:
        payload["retry_count"] = retry_count
    if extra:
        payload.update(extra)
    _log.info(json.dumps(payload, ensure_ascii=False, default=str))


class LatencyTimer:
    __slots__ = ("_t0",)

    def __init__(self) -> None:
        self._t0 = time.perf_counter()

    def ms(self) -> float:
        return (time.perf_counter() - self._t0) * 1000.0


def estimate_chars_as_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def ensure_thiramai_logging() -> None:
    """Attach a stdout handler once so structured JSON lines from log_event are visible."""
    if not _log.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(message)s"))
        _log.addHandler(h)
        _log.setLevel(logging.INFO)
        _log.propagate = False
    http_log = logging.getLogger("thiramai.http")
    if not http_log.handlers:
        hh = logging.StreamHandler()
        hh.setFormatter(logging.Formatter("%(message)s"))
        http_log.addHandler(hh)
        http_log.setLevel(logging.INFO)
        http_log.propagate = False
