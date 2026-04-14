"""Organization membership checks (IDOR prevention)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.models import Role, UserOrganizationMembership
from services.membership_service import membership_for_organization


def verify_org_membership(session: Session, *, user_id: int, organization_id: int) -> bool:
    """True if ``user_id`` has an active membership on ``organization_id``."""
    uid = int(user_id)
    oid = int(organization_id)
    if uid <= 0 or oid <= 0:
        return False
    return membership_for_organization(session, uid, oid) is not None


def validate_user_access(session: Session, user_id: int, organization_id: int) -> bool:
    """
    Guard-layer alias for IDOR prevention: active membership required.

    Use on any code path that accepts a user-chosen ``organization_id`` (query/body/tool args).
    """
    return verify_org_membership(session, user_id=int(user_id), organization_id=int(organization_id))


def get_user_org_ids(session: Session, *, user_id: int) -> list[int]:
    """All organization IDs the user belongs to (active memberships)."""
    uid = int(user_id)
    if uid <= 0:
        return []
    rows = session.scalars(
        select(UserOrganizationMembership.organization_id).where(
            UserOrganizationMembership.user_id == uid,
            UserOrganizationMembership.is_active.is_(True),
        )
    ).all()
    return [int(x) for x in rows if x is not None]


def require_org_role(
    session: Session, *, user_id: int, organization_id: int, allowed_role_names: tuple[str, ...]
) -> bool:
    """True if user's membership role name (lowercased) is one of ``allowed_role_names``."""
    uid = int(user_id)
    oid = int(organization_id)
    if uid <= 0 or oid <= 0 or not allowed_role_names:
        return False
    allowed = {n.strip().lower() for n in allowed_role_names if (n or "").strip()}
    row = session.execute(
        select(Role.name)
        .join(UserOrganizationMembership, UserOrganizationMembership.role_id == Role.id)
        .where(
            UserOrganizationMembership.user_id == uid,
            UserOrganizationMembership.organization_id == oid,
            UserOrganizationMembership.is_active.is_(True),
        )
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return False
    return str(row).strip().lower() in allowed
