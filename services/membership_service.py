"""User ↔ organization ↔ role via ``UserOrganizationMembership`` (Phase 2 multi-tenant identity)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.models import UserOrganizationMembership


def first_active_membership(session: Session, user_id: int) -> UserOrganizationMembership | None:
    """Earliest ``joined_at`` among active memberships (default tenant when JWT omits org)."""
    stmt = (
        select(UserOrganizationMembership)
        .where(
            UserOrganizationMembership.user_id == int(user_id),
            UserOrganizationMembership.is_active.is_(True),
        )
        .order_by(UserOrganizationMembership.joined_at.asc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def membership_for_organization(
    session: Session, user_id: int, organization_id: int
) -> UserOrganizationMembership | None:
    stmt = (
        select(UserOrganizationMembership)
        .where(
            UserOrganizationMembership.user_id == int(user_id),
            UserOrganizationMembership.organization_id == int(organization_id),
            UserOrganizationMembership.is_active.is_(True),
        )
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def list_memberships_for_user(session: Session, user_id: int) -> list[UserOrganizationMembership]:
    stmt = (
        select(UserOrganizationMembership)
        .where(UserOrganizationMembership.user_id == int(user_id))
        .order_by(UserOrganizationMembership.joined_at.asc())
    )
    return list(session.execute(stmt).scalars().all())
