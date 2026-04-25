from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from api.dependencies import CurrentUser, require_owner
from core.database import get_session_factory
from core.db.models import SecurityAuditLog
from core.dangerous_routes import production_blocks_dangerous_routes
from core.settings import get_settings

router = APIRouter(prefix="/security", tags=["Security Status"])


def _count_for_today(event_type: str) -> int:
    factory = get_session_factory()
    if factory is None:
        return 0
    today = datetime.now(timezone.utc).date()
    with factory() as session:
        stmt = select(func.count(SecurityAuditLog.id)).where(
            SecurityAuditLog.event_type == event_type,
            func.date(SecurityAuditLog.created_at) == today,
        )
        out = session.execute(stmt).scalar_one_or_none()
        return int(out or 0)


@router.get("/status")
def security_status(_user: CurrentUser = Depends(require_owner)) -> dict[str, Any]:
    s = get_settings()
    return {
        "dangerous_routes_blocked": production_blocks_dangerous_routes(),
        "rate_limits_active": True,
        "cors_locked": bool(s.cors_allow_origins_list()),
        "auth_required": not bool(s.THIRAMAI_AUTH_DISABLED.strip() == "1" and not s.is_production()),
        "last_audit": datetime.now(timezone.utc).date().isoformat(),
        "blocked_attempts_today": _count_for_today("dangerous_endpoint_attempt") + _count_for_today("ip_blocked"),
        "rate_limited_today": _count_for_today("rate_limit_exceeded"),
    }
