"""
Multi-tenant SaaS: organization provisioning, plan normalization, default business units (departments).

All tenant data paths should scope by ``organization_id`` (see API ``CurrentUser.organization_id`` and JWT).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.auth import hash_password
from core.db.models import Department, Organization, Role, User, UserOrganizationMembership
from core.db.provisioning import provision_new_organization

VALID_SAAS_PLANS: frozenset[str] = frozenset({"free", "pro", "enterprise"})

# Beyond **General** (created by ``provision_new_organization`` / provisioning).
_DEFAULT_BUSINESS_UNITS: tuple[str, ...] = ("Operations", "Sales")


def normalize_plan(plan: str | None) -> str:
    """Return a valid ``organizations.plan`` value (defaults to ``free``)."""
    p = (plan or "free").strip().lower()
    return p if p in VALID_SAAS_PLANS else "free"


def seed_default_business_units(session: Session, organization_id: int) -> int:
    """
    Idempotent: ensure default departments exist (tenant-scoped).

    **General** is created by provisioning; this adds **Operations** and **Sales** when missing.
    """
    oid = int(organization_id)
    added = 0
    for name in _DEFAULT_BUSINESS_UNITS:
        n = (name or "").strip()
        if not n:
            continue
        ct = session.execute(
            select(func.count())
            .select_from(Department)
            .where(Department.organization_id == oid, Department.name == n)
        ).scalar_one()
        if int(ct or 0) > 0:
            continue
        session.add(Department(organization_id=oid, name=n))
        added += 1
    if added:
        session.flush()
    return added


def get_owner_role(session: Session, organization_id: int) -> Role:
    role = session.execute(
        select(Role).where(Role.organization_id == int(organization_id), Role.name == "owner")
    ).scalar_one_or_none()
    if role is None:
        raise RuntimeError("Owner role missing for organization; provisioning incomplete.")
    return role


def create_organization_with_owner(
    session: Session,
    *,
    organization_name: str,
    owner_email: str,
    password: str,
    plan: str = "free",
    gst_number: str | None = None,
    industry: str | None = None,
) -> tuple[Organization, User, Role]:
    """
    Create tenant + RBAC seed + **General** + extra business units + owner user + membership.

    Caller must commit the transaction. Raises ``sqlalchemy.exc.IntegrityError`` on duplicate email.
    """
    email_norm = owner_email.lower().strip()
    org = provision_new_organization(
        session,
        name=organization_name.strip(),
        plan=normalize_plan(plan),
        gst_number=gst_number,
        industry=industry,
    )
    oid = int(org.id)
    seed_default_business_units(session, oid)
    owner_role = get_owner_role(session, oid)
    user = User(
        email=email_norm,
        password_hash=hash_password(password),
        is_active=True,
    )
    session.add(user)
    session.flush()
    session.add(
        UserOrganizationMembership(
            user_id=int(user.id),
            organization_id=oid,
            role_id=int(owner_role.id),
            is_active=True,
        )
    )
    session.flush()
    return org, user, owner_role


def organization_brief_dict(org: Organization) -> dict[str, Any]:
    return {
        "id": int(org.id),
        "name": org.name,
        "plan": normalize_plan(getattr(org, "plan", None) or "free"),
    }
