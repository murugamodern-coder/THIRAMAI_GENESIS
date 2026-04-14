"""
SaaS onboarding: explicit tenant creation (organization + owner + RBAC + default business units).

Prefer this for product flows that name the step “create organization”; behavior matches ``POST /auth/register``
with optional ``plan`` (``free`` | ``pro`` | ``enterprise``).
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.exc import IntegrityError

from api.routes.auth import OrganizationBrief, TokenResponse, access_token_ttl_seconds
from core.auth import create_access_token
from core.database import get_session_factory
from services.audit_log import (
    ACTION_REGISTER,
    client_ip_from_request,
    record_system_audit,
)
from services.org_service import create_organization_with_owner, organization_brief_dict
from services.usage_log_service import ACTION_SIGNUP, log_usage_sync
from services.refresh_token_service import issue_refresh_token

router = APIRouter(prefix="/org", tags=["SaaS & organizations"])


class OrgCreateBody(BaseModel):
    """Create a new tenant and its first owner (same constraints as ``POST /auth/register``)."""

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    organization_name: str = Field(..., min_length=1, max_length=240)
    plan: Literal["free", "pro", "business", "enterprise"] = "free"
    invite_code: str | None = Field(None, max_length=64)


class OrgCreateResponse(TokenResponse):
    """Access token plus organization summary and new user id."""

    organization: OrganizationBrief
    user_id: int


@router.post(
    "/create",
    response_model=OrgCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create organization + owner (SaaS onboarding)",
    description=(
        "Creates ``organizations`` row, seeds roles and permissions, default departments "
        "(General + Operations + Sales), owner user, and membership. Returns JWT with ``active_org_id``."
    ),
)
async def create_organization(request: Request, body: OrgCreateBody) -> OrgCreateResponse:
    ip = client_ip_from_request(request.client.host if request.client else None)
    ua = (request.headers.get("user-agent") or "")[:2000]

    def _work() -> tuple[OrgCreateResponse, int, int]:
        factory = get_session_factory()
        if factory is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DATABASE_URL is not set.",
            )
        try:
            with factory() as session:
                with session.begin():
                    org, user, owner_role = create_organization_with_owner(
                        session,
                        organization_name=body.organization_name,
                        owner_email=str(body.email),
                        password=body.password,
                        plan=body.plan,
                    )
                    inv = (body.invite_code or "").strip()
                    if inv:
                        try:
                            from services.invite_service import peek_invite

                            meta = peek_invite(inv)
                            user.product_profile = {
                                "invite_signup": {"code": inv, "payload": meta or {}},
                            }
                            session.add(user)
                            session.flush()
                        except Exception:
                            pass
                    token = create_access_token(
                        sub_user_id=int(user.id),
                        org_id=int(org.id),
                        active_org_id=int(org.id),
                        role_name=owner_role.name,
                    )
                    refresh_plain = issue_refresh_token(session, user_id=int(user.id))
                    brief = organization_brief_dict(org)
                    return (
                        OrgCreateResponse(
                            access_token=token,
                            expires_in=access_token_ttl_seconds(),
                            refresh_token=refresh_plain,
                            organization=OrganizationBrief(
                                id=int(brief["id"]),
                                name=str(brief["name"]),
                                plan=str(brief["plan"]),
                            ),
                            user_id=int(user.id),
                        ),
                        int(org.id),
                        int(user.id),
                    )
        except IntegrityError as exc:
            record_system_audit(
                action=ACTION_REGISTER,
                outcome="failure",
                organization_id=None,
                client_ip=ip,
                user_agent=ua,
                metadata={"reason": "email_conflict", "channel": "org_create"},
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc

    resp, org_id, user_id = await asyncio.to_thread(_work)
    record_system_audit(
        action=ACTION_REGISTER,
        outcome="success",
        organization_id=org_id,
        user_id=user_id,
        client_ip=ip,
        user_agent=ua,
        metadata={"channel": "org_create", "plan": body.plan},
    )
    log_usage_sync(
        organization_id=org_id,
        user_id=user_id,
        action=ACTION_SIGNUP,
        metadata={"channel": "org_create", "plan": body.plan},
    )
    return resp
