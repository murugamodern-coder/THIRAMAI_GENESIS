"""Operational monitoring JSON endpoints (tenant-scoped auth)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from api.dependencies import CurrentUser, require_permission
from core.rbac import Permission
from services.ai_quality_tracker import get_quality_tracker

router = APIRouter(prefix="/monitoring", tags=["Monitoring"])


@router.get("/ai-quality")
def get_ai_quality_metrics(
    _user: CurrentUser = Depends(require_permission(Permission.AI_ADMIN)),
) -> dict[str, Any]:
    """Rolling-window AI decision quality (in-process; see also Prometheus / Grafana)."""
    return get_quality_tracker().get_quality_metrics()


@router.post("/ai-quality/baseline")
def establish_quality_baseline(
    _user: CurrentUser = Depends(require_permission(Permission.TENANT_ADMIN)),
) -> dict[str, Any]:
    """Capture baseline from current window (owner/admin)."""
    out = get_quality_tracker().establish_baseline()
    if not out.get("ok"):
        return {"status": "error", **out}
    return {"status": "success", "message": "baseline established", **out}


@router.post("/ai-quality/reset-anomalies")
def reset_quality_anomalies(
    _user: CurrentUser = Depends(require_permission(Permission.TENANT_ADMIN)),
) -> dict[str, str]:
    get_quality_tracker().reset_anomaly_count()
    return {"status": "success", "message": "anomaly counter reset"}
