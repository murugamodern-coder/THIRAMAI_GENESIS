"""Multi-organization control: shared intelligence, separate execution lanes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import Organization, UserOrganizationMembership
from services.world_model_engine import build_world_model


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_user_organizations(user_id: int) -> list[dict[str, Any]]:
    factory = _session_factory_or_none()
    if factory is None:
        return []
    with factory() as session:
        rows = (
            session.execute(
                select(UserOrganizationMembership, Organization)
                .join(Organization, Organization.id == UserOrganizationMembership.organization_id)
                .where(
                    UserOrganizationMembership.user_id == int(user_id),
                    UserOrganizationMembership.is_active.is_(True),
                )
                .order_by(Organization.id.asc())
            )
            .all()
        )
    return [
        {
            "organization_id": int(org.id),
            "organization_name": str(org.name or ""),
            "is_disabled": bool(getattr(org, "is_disabled", False)),
            "membership_id": int(mem.id),
            "role_id": int(mem.role_id),
        }
        for mem, org in rows
    ]


def shared_intelligence_context(user_id: int) -> dict[str, Any]:
    orgs = list_user_organizations(int(user_id))
    # Shared layer: one world-model synthesis for the user brain.
    world = build_world_model(int(user_id))
    return {"ok": True, "updated_at": _now_iso(), "organizations": orgs, "shared_intelligence": world}


def separate_execution_plan(user_id: int) -> dict[str, Any]:
    orgs = list_user_organizations(int(user_id))
    lanes = []
    for org in orgs:
        lanes.append(
            {
                "organization_id": int(org["organization_id"]),
                "execution_lane": f"org_{int(org['organization_id'])}",
                "is_enabled": not bool(org.get("is_disabled")),
                "policy": {"shared_intelligence": True, "separate_execution": True},
            }
        )
    return {"ok": True, "lanes": lanes, "generated_at": _now_iso()}
