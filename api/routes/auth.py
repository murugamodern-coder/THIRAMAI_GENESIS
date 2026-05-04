"""
Authentication router: register (org + owner) and login (JWT Bearer).

Main endpoints:
  POST /auth/register — create organization + Owner user, return access token.
  POST /auth/login    — verify email/password via DB, return Bearer JWT (OAuth2 password form).

Also exposes GET /auth/me and seed_default_roles_on_startup() for the rest of the app.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.dependencies import CurrentUser, get_current_user
from core.auth import create_access_token, verify_password
from core.database import get_session_factory
from core.db.models import Organization, Role, User, UserOrganizationMembership
from core.db.provisioning import ensure_organization_id_one_exists, ensure_tenant_defaults
from services.org_service import create_organization_with_owner
from services.usage_log_service import ACTION_LOGIN, ACTION_SIGNUP, log_usage_sync
from services.audit_log import (
    ACTION_LOGIN_FAILURE,
    ACTION_LOGIN_SUCCESS,
    ACTION_REGISTER,
    client_ip_from_request,
    record_system_audit,
)
from services.security_audit import EVENT_FAILED_LOGIN, record_security_audit_event
from services.membership_service import first_active_membership, membership_for_organization
from services.refresh_token_service import (
    issue_refresh_token,
    load_valid_refresh_row,
    membership_context_for_refresh,
)

# Module-level TTL for ``TokenResponse.expires_in`` (must work inside ``asyncio.to_thread`` closures).
try:
    from core.auth import access_token_ttl_seconds as _access_token_ttl_seconds_impl
except ImportError:  # pragma: no cover

    def _access_token_ttl_seconds_impl() -> int:
        return 86400


def access_token_ttl_seconds() -> int:
    """86400 s = 24 h when ``JWT_ACCESS_EXPIRE_MINUTES=1440`` (stable fallback if core import fails)."""
    try:
        return int(_access_token_ttl_seconds_impl())
    except Exception:
        return 86400

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


class RegisterRequest(BaseModel):
    """Payload to create a new tenant and its first Owner account."""

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    organization_name: str = Field(..., min_length=1, max_length=240)
    invite_code: str | None = Field(None, max_length=64, description="Optional referral from /signup?ref=")


class TokenResponse(BaseModel):
    """Use access_token as Authorization: Bearer <token>. Refresh when access expires via POST /auth/refresh."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Access JWT lifetime in seconds")
    refresh_token: str | None = Field(None, description="Opaque refresh token (store securely client-side)")


class RefreshTokenBody(BaseModel):
    refresh_token: str = Field(..., min_length=24, max_length=512)


class OrganizationBrief(BaseModel):
    id: int
    name: str
    plan: str


class RoleBrief(BaseModel):
    id: int
    name: str
    level: int


class UserMeResponse(BaseModel):
    id: int
    email: str
    is_active: bool
    organization: OrganizationBrief
    role: RoleBrief


def ensure_roles_seeded(session: Session, organization_id: int) -> None:
    """Ensure default roles + General department exist (idempotent)."""
    ensure_tenant_defaults(session, organization_id)


def get_user_roles(session: Session, user_id: int) -> list[dict[str, Any]]:
    """
    Fetch all roles for a user across all their organization memberships.
    
    Returns a list of role dictionaries with id, name, level, and organization_id.
    """
    stmt = select(
        Role.id,
        Role.name,
        Role.level,
        Role.organization_id,
        Organization.name.label("organization_name")
    ).select_from(
        UserOrganizationMembership
    ).join(
        Role, UserOrganizationMembership.role_id == Role.id
    ).join(
        Organization, UserOrganizationMembership.organization_id == Organization.id
    ).where(
        UserOrganizationMembership.user_id == user_id
    )
    
    result = session.execute(stmt)
    roles = []
    for row in result:
        roles.append({
            "id": int(row.id),
            "name": row.name,
            "level": int(row.level),
            "organization_id": int(row.organization_id),
            "organization_name": row.organization_name,
        })
    return roles


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register organization + owner",
    description="Creates a new tenant, seeds RBAC, returns JWT. Rate-limited with other /auth routes.",
)
async def register(request: Request, body: RegisterRequest) -> TokenResponse:
    """
    Create a new organization and an Owner user in one transaction, then return a JWT.

    Uses ``services.org_service.create_organization_with_owner`` and ``create_access_token``.
    """
    email_norm = body.email.lower().strip()
    ip = client_ip_from_request(request.client.host if request.client else None)
    ua = (request.headers.get("user-agent") or "")[:2000]

    def _work() -> tuple[TokenResponse, int, int]:
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
                        organization_name=body.organization_name.strip(),
                        owner_email=email_norm,
                        password=body.password,
                        plan="free",
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
                    return (
                        TokenResponse(
                            access_token=token,
                            expires_in=access_token_ttl_seconds(),
                            refresh_token=refresh_plain,
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
                metadata={"reason": "email_conflict", "channel": "auth_register"},
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

    token_resp, org_id, user_id = await asyncio.to_thread(_work)
    record_system_audit(
        action=ACTION_REGISTER,
        outcome="success",
        organization_id=org_id,
        user_id=user_id,
        client_ip=ip,
        user_agent=ua,
        metadata={"channel": "auth_register"},
    )
    log_usage_sync(
        organization_id=org_id,
        user_id=user_id,
        action=ACTION_SIGNUP,
        metadata={"channel": "auth_register"},
    )
    return token_resp


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="OAuth2 password login",
    description=(
        "Form body: ``username`` = email **or** unique ``users.username``, ``password`` = password. "
        "Returns ``access_token`` (JWT). "
        "Send as ``application/x-www-form-urlencoded``. Used by Command Center SPA and "
        "``templates/dashboard.html`` (Personal AI OS)."
    ),
)
async def login(request: Request, form: Annotated[OAuth2PasswordRequestForm, Depends()]) -> TokenResponse:
    """
    Verify credentials against the database session; return a Bearer JWT (token_type=bearer).

    Send as application/x-www-form-urlencoded: username=<email>, password=<password>.
    """
    raw_login = (form.username or "").strip()
    email_norm = raw_login.lower() if "@" in raw_login else ""
    username_norm = raw_login.lower() if "@" not in raw_login and raw_login else ""
    ip = client_ip_from_request(request.client.host if request.client else None)
    ua = (request.headers.get("user-agent") or "")[:2000]

    def _work() -> TokenResponse:
        factory = get_session_factory()
        if factory is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DATABASE_URL is not set.",
            )
        with factory() as session:
            if email_norm:
                user = session.execute(select(User).where(User.email == email_norm)).scalar_one_or_none()
            elif username_norm:
                user = session.execute(
                    select(User).where(func.lower(User.username) == username_norm)
                ).scalar_one_or_none()
            else:
                user = None
            if user is None or not verify_password(form.password, user.password_hash):
                record_system_audit(
                    action=ACTION_LOGIN_FAILURE,
                    outcome="failure",
                    organization_id=None,
                    user_id=None,
                    client_ip=ip,
                    user_agent=ua,
                    metadata={"reason": "bad_credentials", "channel": "auth_login"},
                )
                record_security_audit_event(
                    event_type=EVENT_FAILED_LOGIN,
                    user_id=None,
                    ip_address=ip,
                    path="/auth/login",
                    details={"reason": "bad_credentials", "channel": "auth_login"},
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Incorrect email or password",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            if not user.is_active:
                record_system_audit(
                    action=ACTION_LOGIN_FAILURE,
                    outcome="failure",
                    organization_id=None,
                    user_id=int(user.id),
                    client_ip=ip,
                    user_agent=ua,
                    metadata={"reason": "inactive", "channel": "auth_login"},
                )
                record_security_audit_event(
                    event_type=EVENT_FAILED_LOGIN,
                    user_id=int(user.id),
                    ip_address=ip,
                    path="/auth/login",
                    details={"reason": "inactive", "channel": "auth_login"},
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User is inactive",
                )
            mem = first_active_membership(session, int(user.id))
            if mem is None:
                record_system_audit(
                    action=ACTION_LOGIN_FAILURE,
                    outcome="failure",
                    organization_id=None,
                    user_id=int(user.id),
                    client_ip=ip,
                    user_agent=ua,
                    metadata={"reason": "no_membership", "channel": "auth_login"},
                )
                record_security_audit_event(
                    event_type=EVENT_FAILED_LOGIN,
                    user_id=int(user.id),
                    ip_address=ip,
                    path="/auth/login",
                    details={"reason": "no_membership", "channel": "auth_login"},
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="No organization membership",
                )
            role = session.get(Role, int(mem.role_id))
            if role is None:
                record_system_audit(
                    action=ACTION_LOGIN_FAILURE,
                    outcome="failure",
                    organization_id=int(mem.organization_id),
                    user_id=int(user.id),
                    client_ip=ip,
                    user_agent=ua,
                    metadata={"reason": "role_missing", "channel": "auth_login"},
                )
                record_security_audit_event(
                    event_type=EVENT_FAILED_LOGIN,
                    user_id=int(user.id),
                    ip_address=ip,
                    path="/auth/login",
                    details={"reason": "role_missing", "channel": "auth_login"},
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Role missing",
                )
            try:
                token = create_access_token(
                    sub_user_id=int(user.id),
                    org_id=int(mem.organization_id),
                    active_org_id=int(mem.organization_id),
                    role_name=role.name,
                )
            except RuntimeError as exc:
                record_system_audit(
                    action=ACTION_LOGIN_FAILURE,
                    outcome="failure",
                    organization_id=int(mem.organization_id),
                    user_id=int(user.id),
                    client_ip=ip,
                    user_agent=ua,
                    metadata={"reason": "token_error", "channel": "auth_login"},
                )
                record_security_audit_event(
                    event_type=EVENT_FAILED_LOGIN,
                    user_id=int(user.id),
                    ip_address=ip,
                    path="/auth/login",
                    details={"reason": "token_error", "channel": "auth_login"},
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=str(exc),
                ) from exc
            record_system_audit(
                action=ACTION_LOGIN_SUCCESS,
                outcome="success",
                organization_id=int(mem.organization_id),
                user_id=int(user.id),
                client_ip=ip,
                user_agent=ua,
                metadata={"channel": "auth_login"},
            )
            log_usage_sync(
                organization_id=int(mem.organization_id),
                user_id=int(user.id),
                action=ACTION_LOGIN,
                metadata={"channel": "auth_login"},
            )
            refresh_plain = issue_refresh_token(session, user_id=int(user.id))
            return TokenResponse(
                access_token=token,
                expires_in=access_token_ttl_seconds(),
                refresh_token=refresh_plain,
            )

    return await asyncio.to_thread(_work)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Rotate access JWT using refresh token",
    description="Body JSON: refresh_token. Returns new access_token + new refresh_token (previous refresh is revoked).",
)
async def refresh_session(body: RefreshTokenBody) -> TokenResponse:
    def _work() -> TokenResponse:
        factory = get_session_factory()
        if factory is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DATABASE_URL is not set.",
            )
        with factory() as session:
            with session.begin():
                row = load_valid_refresh_row(session, plain=body.refresh_token)
                if row is None:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid or expired refresh token",
                    )
                ctx = membership_context_for_refresh(session, user_id=int(row.user_id))
                if ctx is None:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="User inactive or membership missing",
                    )
                _u, mem, role = ctx
                row.revoked_at = datetime.now(timezone.utc)
                session.flush()
                new_refresh = issue_refresh_token(session, user_id=int(_u.id))
                access = create_access_token(
                    sub_user_id=int(_u.id),
                    org_id=int(mem.organization_id),
                    active_org_id=int(mem.organization_id),
                    role_name=role.name,
                )
                return TokenResponse(
                    access_token=access,
                    expires_in=access_token_ttl_seconds(),
                    refresh_token=new_refresh,
                )

    return await asyncio.to_thread(_work)


@router.get(
    "/me",
    response_model=UserMeResponse,
    summary="Current user and organization",
    description="Requires Bearer token; returns org and role for JWT-bound tenant.",
)
async def me(user: Annotated[CurrentUser, Depends(get_current_user)]) -> UserMeResponse:
    """Current user profile (requires Authorization: Bearer)."""

    if user.id == 0:
        return UserMeResponse(
            id=0,
            email=user.email,
            is_active=True,
            organization=OrganizationBrief(
                id=user.organization_id,
                name="dev-organization",
                plan="free",
            ),
            role=RoleBrief(id=0, name=user.role_name, level=user.role_level),
        )

    def _work() -> UserMeResponse:
        factory = get_session_factory()
        if factory is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DATABASE_URL is not set",
            )
        with factory() as session:
            u = session.get(User, user.id)
            if u is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
            mem = membership_for_organization(session, int(u.id), int(user.organization_id))
            if mem is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Membership not found for active organization",
                )
            org = session.get(Organization, int(user.organization_id))
            role = session.get(Role, int(mem.role_id))
            if org is None or role is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Data integrity error",
                )
            if int(role.organization_id) != int(mem.organization_id):
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Role is not scoped to the membership organization",
                )
            return UserMeResponse(
                id=int(u.id),
                email=u.email,
                is_active=bool(u.is_active),
                organization=OrganizationBrief(
                    id=int(org.id), name=org.name, plan=getattr(org, "plan", None) or "free"
                ),
                role=RoleBrief(id=int(role.id), name=role.name, level=int(role.level)),
            )

    return await asyncio.to_thread(_work)


def seed_default_roles_on_startup() -> None:
    """Called from app startup: ensure every organization has default roles + General department."""
    factory = get_session_factory()
    if factory is None:
        return
    try:
        with factory() as session:
            with session.begin():
                ensure_organization_id_one_exists(session)
                for org in session.execute(select(Organization)).scalars().all():
                    ensure_tenant_defaults(session, int(org.id))
    except Exception:
        pass
