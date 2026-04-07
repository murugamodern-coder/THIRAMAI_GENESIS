"""
Phase 2 — multi-business identity: list org memberships and switch active tenant (JWT ``active_org_id``).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel

from api.dependencies import CurrentUser, get_current_user
from api.routes.auth import OrganizationBrief, RoleBrief, TokenResponse
from core.auth import access_token_ttl_seconds, create_access_token
from core.database import get_session_factory
from sqlalchemy import select

from core.db.models import Organization, Role
from services.membership_service import list_memberships_for_user, membership_for_organization

router = APIRouter(prefix="/me", tags=["Tenancy & organizations"])


class MembershipListItem(BaseModel):
    organization: OrganizationBrief
    role: RoleBrief
    is_active: bool
    joined_at: datetime
    is_current: bool


@router.get("/organizations", response_model=list[MembershipListItem])
async def list_my_organizations(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> list[MembershipListItem]:
    """All organizations the user belongs to, with role and whether it matches the active JWT context."""
    def _work() -> list[MembershipListItem]:
        factory = get_session_factory()
        if factory is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DATABASE_URL is not set.",
            )
        with factory() as session:
            if int(user.id) == 0:
                orgs = list(session.execute(select(Organization).order_by(Organization.id.asc())).scalars().all())
                out_dev: list[MembershipListItem] = []
                for org in orgs:
                    cur = int(org.id) == int(user.organization_id)
                    out_dev.append(
                        MembershipListItem(
                            organization=OrganizationBrief(
                                id=int(org.id),
                                name=org.name,
                                plan=getattr(org, "plan", None) or "free",
                            ),
                            role=RoleBrief(id=0, name="owner", level=1),
                            is_active=True,
                            joined_at=getattr(org, "created_at", None) or datetime.now(timezone.utc),
                            is_current=cur,
                        )
                    )
                return out_dev

            memberships = list_memberships_for_user(session, int(user.id))
            out: list[MembershipListItem] = []
            for m in memberships:
                org = session.get(Organization, int(m.organization_id))
                role = session.get(Role, int(m.role_id))
                if org is None or role is None:
                    continue
                out.append(
                    MembershipListItem(
                        organization=OrganizationBrief(
                            id=int(org.id),
                            name=org.name,
                            plan=getattr(org, "plan", None) or "free",
                        ),
                        role=RoleBrief(id=int(role.id), name=role.name, level=int(role.level)),
                        is_active=bool(m.is_active),
                        joined_at=m.joined_at,
                        is_current=int(m.organization_id) == int(user.organization_id),
                    )
                )
            return out

    return await asyncio.to_thread(_work)


@router.post("/switch-organization/{org_id}", response_model=TokenResponse)
async def switch_organization(
    org_id: Annotated[int, Path(..., ge=1, description="Target organizations.id")],
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> TokenResponse:
    """Validate membership, then return a new JWT with ``active_org_id`` = ``org_id``."""
    if user.id == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization switch is not available in auth-disabled dev mode.",
        )

    def _work() -> TokenResponse:
        factory = get_session_factory()
        if factory is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DATABASE_URL is not set.",
            )
        with factory() as session:
            mem = membership_for_organization(session, int(user.id), int(org_id))
            if mem is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You are not an active member of this organization.",
                )
            role = session.get(Role, int(mem.role_id))
            if role is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Role missing for membership",
                )
            token = create_access_token(
                sub_user_id=int(user.id),
                org_id=int(org_id),
                active_org_id=int(org_id),
                role_name=role.name,
            )
            return TokenResponse(
                access_token=token,
                expires_in=access_token_ttl_seconds(),
                refresh_token=None,
            )

    return await asyncio.to_thread(_work)
