"""Distributed tracing initialiser — fully optional OpenTelemetry.

Why this module is opt-in:

* OpenTelemetry SDK + instrumentations add ~80 MB of wheels and pull GRPC,
  protobuf, etc. They are **not** in ``requirements-base.txt`` to keep the
  Docker image tight.
* :func:`init_tracing` therefore:

  1. Returns early as a no-op when ``THIRAMAI_TRACING_ENABLED`` is not
     truthy. Default OFF.
  2. Performs every ``opentelemetry`` import inside the function so an
     unset / partial install does not break ``app.py`` boot.
  3. Catches any import or instrumentation error and downgrades to a
     no-op while logging a single warning.

Environment variables:

* ``THIRAMAI_TRACING_ENABLED``  : ``1/true/yes/on`` to turn on. Default: off.
* ``OTEL_EXPORTER_OTLP_ENDPOINT``: collector endpoint, e.g. ``http://otel-collector:4317``.
* ``OTEL_SERVICE_NAME``         : overrides the default ``thiramai-api``.
* ``OTEL_TRACES_SAMPLER_RATIO`` : fraction (0.0-1.0). Default ``0.1``.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


_TRUTHY = {"1", "true", "yes", "on"}


def _is_enabled() -> bool:
    raw = (os.getenv("THIRAMAI_TRACING_ENABLED") or "").strip().lower()
    return raw in _TRUTHY


def _service_name() -> str:
    return (os.getenv("OTEL_SERVICE_NAME") or "thiramai-api").strip() or "thiramai-api"


def _sampler_ratio() -> float:
    try:
        return max(0.0, min(1.0, float(os.getenv("OTEL_TRACES_SAMPLER_RATIO") or "0.1")))
    except (TypeError, ValueError):
        return 0.1


def init_tracing(app: "FastAPI", *, service_name: str | None = None) -> dict[str, Any]:
    """Initialise OpenTelemetry tracing for ``app``.

    Returns a small status dict for log lines / smoke checks. Never raises.
    """
    if not _is_enabled():
        return {"ok": True, "enabled": False, "reason": "tracing_disabled"}

    name = (service_name or _service_name()).strip() or "thiramai-api"

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
    except Exception as exc:
        logger.warning("tracing disabled: opentelemetry-sdk import failed (%s)", exc)
        return {"ok": False, "enabled": False, "reason": f"sdk_import_failed: {exc}"}

    # Build provider + sampler
    try:
        resource = Resource.create({"service.name": name})
        sampler = TraceIdRatioBased(_sampler_ratio())
        provider = TracerProvider(resource=resource, sampler=sampler)
        trace.set_tracer_provider(provider)
    except Exception as exc:
        logger.warning("tracing provider setup failed: %s", exc)
        return {"ok": False, "enabled": False, "reason": f"provider_failed: {exc}"}

    # Exporter — optional. If grpc OTLP isn't installed we skip gracefully.
    exporter_status = "no_exporter"
    endpoint = (os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip()
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(endpoint=endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            exporter_status = "otlp_grpc"
        except Exception as exc:
            logger.warning("tracing OTLP exporter unavailable (%s) — spans will be in-memory only", exc)

    # Auto-instrument FastAPI / SQLAlchemy / Redis where available. Each is
    # individually optional.
    instrumented: list[str] = []
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        instrumented.append("fastapi")
    except Exception as exc:
        logger.debug("FastAPIInstrumentor unavailable: %s", exc)

    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        SQLAlchemyInstrumentor().instrument()
        instrumented.append("sqlalchemy")
    except Exception as exc:
        logger.debug("SQLAlchemyInstrumentor unavailable: %s", exc)

    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor

        RedisInstrumentor().instrument()
        instrumented.append("redis")
    except Exception as exc:
        logger.debug("RedisInstrumentor unavailable: %s", exc)

    logger.info(
        "tracing initialised service=%s exporter=%s instrumented=%s sampler=%.2f",
        name,
        exporter_status,
        ",".join(instrumented) or "none",
        _sampler_ratio(),
    )
    return {
        "ok": True,
        "enabled": True,
        "service_name": name,
        "exporter": exporter_status,
        "instrumented": instrumented,
        "sampler_ratio": _sampler_ratio(),
    }


def get_tracer(name: str = "thiramai"):
    """Return an OpenTelemetry tracer or a no-op stub when tracing is disabled.

    Code can call ``with get_tracer(__name__).start_as_current_span("foo"):``
    unconditionally — the no-op stub satisfies the same context-manager API.
    """
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except Exception:
        return _NoOpTracer()


class _NoOpSpan:
    """Stub span used when OpenTelemetry is missing."""

    def __enter__(self) -> "_NoOpSpan":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def set_attribute(self, *_a: Any, **_kw: Any) -> None:
        return None

    def add_event(self, *_a: Any, **_kw: Any) -> None:
        return None

    def record_exception(self, *_a: Any, **_kw: Any) -> None:
        return None

    def set_status(self, *_a: Any, **_kw: Any) -> None:
        return None


class _NoOpTracer:
    """Stub tracer compatible with the OpenTelemetry start_as_current_span API."""

    def start_as_current_span(self, *_a: Any, **_kw: Any) -> _NoOpSpan:
        return _NoOpSpan()

    def start_span(self, *_a: Any, **_kw: Any) -> _NoOpSpan:
        return _NoOpSpan()


__all__ = ["get_tracer", "init_tracing"]
