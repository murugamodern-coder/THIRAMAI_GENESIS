"""
Prometheus-style text metrics for THIRAMAI autonomy (does not replace Instrumentator ``/metrics``).

Scrape ``GET /metrics/thiramai`` alongside the default app metrics at ``/metrics``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from api.dependencies import CurrentUser, require_owner

router = APIRouter(tags=["THIRAMAI Metrics"])


@router.get("/metrics/thiramai", include_in_schema=True)
def thiramai_prometheus_metrics(_user: CurrentUser = Depends(require_owner)) -> Response:
    from thiramai.runtime import ai_observability

    _ = _user
    body = ai_observability.prometheus_text()
    return Response(content=body, media_type="text/plain; charset=utf-8")
