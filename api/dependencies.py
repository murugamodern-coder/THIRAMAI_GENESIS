"""
FastAPI dependencies: resolve JWT → current user and enforce role hierarchy.

Role hierarchy (numeric level on Role row): owner=1, manager=2, supervisor=3, worker=4.
Lower level number = higher privilege. A user passes `require_roles("manager", "supervisor")` if
their level is <= the worst (highest number) among the named roles — i.e. owner and manager also pass.
"""

from __future__ import annotations

import asyncio
import inspect
import os
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.requests import Request
from jose import JWTError
from jose.exceptions import ExpiredSignatureError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.auth import decode_access_token, token_subject_user_id
from core.database import get_session_factory, set_current_org_id, tenant_session_scope
from core.permission_engine import has_permission
from core.production_safety import is_production_environment
from core.db.models import Organization, Role, User
from core.rbac import Permission
from services.membership_service import first_active_membership, membership_for_organization

# Bearer scheme: auto_error=False so we can support dev bypass without a header.
_bearer = HTTPBearer(auto_error=False)

# Canonical role name → privilege level (must match seeded `roles.level`).
ROLE_LEVEL_BY_NAME: dict[str, int] = {
    "superadmin": 0,
    "owner": 1,
    "admin": 1,
    "manager": 2,
    "supervisor": 3,
    "worker": 4,
    "staff": 4,
    "customer": 5,
    # Read-only dashboards / AI goal observers (narrow route allowlists in routers).
    "viewer": 6,
}


class CurrentUser(BaseModel):
    """Authenticated principal extracted from JWT + database."""

    model_config = {"frozen": True}

    id: int = Field(..., description="users.id")
    email: str
    organization_id: int
    role_name: str
    role_level: int
    is_active: bool = True


def _auth_disabled() -> bool:
    """
    When true, unauthenticated requests receive a synthetic dev principal (``THIRAMAI_AUTH_DISABLED=1``).

    Always false in production (defense in depth alongside ``assert_safe_production_config``).
    """
    if is_production_environment():
        return False
    return (os.getenv("THIRAMAI_AUTH_DISABLED") or "").strip() == "1"


def _dev_principal(request: Request) -> CurrentUser:
    """
    Synthetic owner used only when THIRAMAI_AUTH_DISABLED=1 and no Bearer token is sent.
    Point THIRAMAI_DEV_ORG_ID at a real organizations.id for billing tests.

    Optional header ``X-THIRAMAI-DEV-ORG-ID`` overrides the active tenant (dev / LAN only; ignored in production).
    """
    org_id = int((os.getenv("THIRAMAI_DEV_ORG_ID") or "1").strip() or "1")
    if not is_production_environment():
        raw = (request.headers.get("X-THIRAMAI-DEV-ORG-ID") or "").strip()
        if raw.isdigit():
            org_id = int(raw)
    return CurrentUser(
        id=0,
        email="dev-bypass@local",
        organization_id=org_id,
        role_name="owner",
        role_level=1,
        is_active=True,
    )


def _load_user_session(session: Session, user_id: int) -> User | None:
    """Fetch user with role row for authorization checks."""
    stmt = select(User).where(User.id == user_id)
    return session.execute(stmt).scalar_one_or_none()


def _user_to_principal(u: User, role: Role, *, active_organization_id: int) -> CurrentUser:
    """Map ORM rows to a small Pydantic principal (active tenant = JWT ``active_org_id``)."""
    return CurrentUser(
        id=int(u.id),
        email=u.email,
        organization_id=int(active_organization_id),
        role_name=role.name.lower(),
        role_level=int(role.level),
        is_active=bool(u.is_active),
    )


def _claim_active_org_raw(claims: dict) -> str:
    """Prefer explicit ``active_org_id``; fall back to legacy ``org_id``."""
    for key in ("active_org_id", "org_id"):
        raw = claims.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return ""


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser:
    """
    Validate Authorization: Bearer <JWT>, load user from DB, return CurrentUser.

    Raises 401 if token is missing/invalid, user inactive, or JWT claims disagree with DB.
    When THIRAMAI_AUTH_DISABLED=1 and no Bearer token is provided, returns a dev owner principal.
    """
    if credentials is None or not credentials.credentials:
        if _auth_disabled():
            return _dev_principal(request)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials.strip()

    def _resolve() -> CurrentUser:
        factory = get_session_factory()
        if factory is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database is not configured (DATABASE_URL).",
            )
        try:
            claims = decode_access_token(token)
            uid = token_subject_user_id(claims)
        except ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        with factory() as session:
            u = _load_user_session(session, uid)
            if u is None or not u.is_active:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found or inactive",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            claim_org_raw = _claim_active_org_raw(claims)
            mem = None
            if claim_org_raw:
                try:
                    want_oid = int(claim_org_raw)
                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid organization in token",
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                mem = membership_for_organization(session, int(u.id), want_oid)
                if mem is None:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Not a member of this organization",
                        headers={"WWW-Authenticate": "Bearer"},
                    )
            else:
                mem = first_active_membership(session, int(u.id))
                if mem is None:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="No organization membership",
                        headers={"WWW-Authenticate": "Bearer"},
                    )

            role = session.get(Role, int(mem.role_id))
            if role is None:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Role not found")
            if int(role.organization_id) != int(mem.organization_id):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Role does not belong to membership organization",
                )

            claim_role = (claims.get("role") or "").strip().lower()
            if claim_role and role.name.lower() != claim_role:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token role mismatch",
                )

            # SaaS kill switch: block disabled orgs (strict isolation & provider control).
            org = session.get(Organization, int(mem.organization_id))
            if org is not None and bool(getattr(org, "is_disabled", False)):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization is disabled")

            principal = _user_to_principal(u, role, active_organization_id=int(mem.organization_id))
            set_current_org_id(int(principal.organization_id))
            return principal

    return await asyncio.to_thread(_resolve)


def _dev_principal_ws() -> CurrentUser:
    """
    Synthetic owner for WebSocket when ``THIRAMAI_AUTH_DISABLED=1`` and no token is sent.

    Unlike ``_dev_principal(Request)``, there is no request header override for org — use env only.
    """
    org_id = int((os.getenv("THIRAMAI_DEV_ORG_ID") or "1").strip() or "1")
    return CurrentUser(
        id=0,
        email="dev-bypass@local",
        organization_id=org_id,
        role_name="owner",
        role_level=1,
        is_active=True,
    )


def try_resolve_current_user_from_access_token(token: str | None) -> CurrentUser | None:
    """
    Resolve a raw JWT access token string to ``CurrentUser`` (for WebSocket ``?token=``).

    Returns ``None`` when the token is missing/invalid, the DB session factory is unavailable,
    or the user cannot be resolved. When auth is disabled and the token is empty/whitespace,
    returns the dev-bypass principal (same semantics as HTTP with no Bearer header).
    """
    raw = (token or "").strip()
    if not raw:
        if _auth_disabled():
            return _dev_principal_ws()
        return None

    try:
        claims = decode_access_token(raw)
        uid = token_subject_user_id(claims)
    except ExpiredSignatureError:
        return None
    except JWTError:
        return None

    factory = get_session_factory()
    if factory is None:
        return None

    try:
        with factory() as session:
            u = _load_user_session(session, uid)
            if u is None or not u.is_active:
                return None

            claim_org_raw = _claim_active_org_raw(claims)
            mem = None
            if claim_org_raw:
                try:
                    want_oid = int(claim_org_raw)
                except ValueError:
                    return None
                mem = membership_for_organization(session, int(u.id), want_oid)
                if mem is None:
                    return None
            else:
                mem = first_active_membership(session, int(u.id))
                if mem is None:
                    return None

            role = session.get(Role, int(mem.role_id))
            if role is None:
                return None
            if int(role.organization_id) != int(mem.organization_id):
                return None

            claim_role = (claims.get("role") or "").strip().lower()
            if claim_role and role.name.lower() != claim_role:
                return None

            return _user_to_principal(u, role, active_organization_id=int(mem.organization_id))
    except Exception:
        return None


async def get_current_user_optional(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser | None:
    """
    Same as ``get_current_user`` when credentials are valid or dev bypass applies; otherwise ``None``
    (no 401). Used for routes that also accept ``THIRAMAI_DASHBOARD_ACTION_TOKEN`` LAN flows.
    """
    if credentials is None or not credentials.credentials:
        if _auth_disabled():
            return _dev_principal(request)
        return None
    try:
        return await get_current_user(credentials)
    except HTTPException:
        return None


def _max_level_for_allowed_roles(allowed_role_names: tuple[str, ...]) -> int:
    """Worst (highest numeric) level among allowed role names — users at or above that pass."""
    levels: list[int] = []
    for name in allowed_role_names:
        key = name.strip().lower()
        if key not in ROLE_LEVEL_BY_NAME:
            raise ValueError(f"Unknown role name: {name}")
        levels.append(ROLE_LEVEL_BY_NAME[key])
    return max(levels)


def require_roles(*allowed_role_names: str) -> Callable[..., CurrentUser]:
    """
    Build a FastAPI dependency that requires the caller's role level to be at least as privileged
    as the weakest role in the allowlist (hierarchy: owner ⊃ manager ⊃ supervisor ⊃ worker).

    Example: require_roles("owner", "manager") allows owner (1) and manager (2), blocks supervisor (3).
    """

    allowed = tuple(allowed_role_names)
    max_allowed_level = _max_level_for_allowed_roles(allowed)

    async def _dep(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        """
        Enforce RBAC: 403 if the user's role level is stricter (higher number) than allowed.
        """
        if user.role_level > max_allowed_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(allowed)} (or higher privilege)",
            )
        return user

    return _dep


async def require_owner(current_user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
    """Only OWNER/ADMIN tier can access."""
    role = (current_user.role_name or "").strip().lower()
    if role not in {"owner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner access required")
    return current_user


async def require_staff(current_user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
    """Operational staff tier (owner/admin/manager/supervisor/staff/worker)."""
    role = (current_user.role_name or "").strip().lower()
    if role not in {"owner", "admin", "manager", "supervisor", "staff", "worker"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff access required")
    return current_user


async def require_any_role(current_user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
    """Any authenticated business workspace user."""
    role = (current_user.role_name or "").strip().lower()
    if role in {"customer", "family"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Business workspace access required")
    return current_user


def require_exact_role(role_name: str) -> Callable[..., CurrentUser]:
    """
    JWT user must match role name exactly (case-insensitive), e.g. ``require_exact_role("admin")``.
    Unlike ``require_roles``, this does **not** allow higher-privilege roles such as owner.
    """

    want = (role_name or "").strip().lower()

    async def _dep(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if user.role_name.lower() != want:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {role_name}",
            )
        return user

    return _dep


def _normalize_permission_values(*permissions: Permission | str) -> tuple[str, ...]:
    out: list[str] = []
    for p in permissions:
        if isinstance(p, Permission):
            out.append(p.value)
        else:
            raw = str(p or "").strip()
            if raw:
                out.append(raw)
    vals = tuple(dict.fromkeys(out))
    if not vals:
        raise ValueError("require_permission needs at least one permission")
    return vals


def require_permission(*permissions: Permission | str) -> Callable[..., CurrentUser]:
    """
    Require the caller's role to include at least one of the given permissions.

    Prefer this for resource-specific checks; use ``require_roles`` for coarse hierarchy gates.

    Supports two styles:
    - FastAPI dependency: ``Depends(require_permission(Permission.INVENTORY_READ))``
    - Decorator style: ``@require_permission("view_business")`` (expects route function to receive
      ``user``/``_user``/``current_user`` or ``request`` with ``request.state.current_user`` set).
    """
    perms = _normalize_permission_values(*permissions)

    def _check_user(user: CurrentUser) -> None:
        ok = any(has_permission(user, p) for p in perms)
        if ok:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing permission: one of {list(perms)}",
        )

    def _extract_user_for_decorator(args: tuple[object, ...], kwargs: dict[str, object]) -> CurrentUser | None:
        for key in ("user", "_user", "current_user"):
            candidate = kwargs.get(key)
            if isinstance(candidate, CurrentUser):
                return candidate
        req = kwargs.get("request")
        if isinstance(req, Request):
            candidate = getattr(req.state, "current_user", None)
            if isinstance(candidate, CurrentUser):
                return candidate
        for a in args:
            if isinstance(a, Request):
                candidate = getattr(a.state, "current_user", None)
                if isinstance(candidate, CurrentUser):
                    return candidate
            if isinstance(a, CurrentUser):
                return a
        return None

    async def _dep(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        # Decorator mode: @require_permission("view_business")
        if callable(user) and not isinstance(user, CurrentUser):
            fn = user

            if inspect.iscoroutinefunction(fn):
                async def _wrapped_async(*args, **kwargs):
                    principal = _extract_user_for_decorator(args, kwargs)
                    if principal is None:
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Not authenticated",
                        )
                    _check_user(principal)
                    return await fn(*args, **kwargs)
                return _wrapped_async  # type: ignore[return-value]

            def _wrapped_sync(*args, **kwargs):
                principal = _extract_user_for_decorator(args, kwargs)
                if principal is None:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Not authenticated",
                    )
                _check_user(principal)
                return fn(*args, **kwargs)
            return _wrapped_sync  # type: ignore[return-value]

        if not isinstance(user, CurrentUser):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            _check_user(user)
        except HTTPException:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: one of {list(perms)}",
            )
        return user

    return _dep


def ensure_org_membership(user: CurrentUser, organization_id: int) -> None:
    """
    Raise 403 unless the user has an active membership on ``organization_id``.

    When ``organization_id`` equals the JWT active org, skips a DB lookup.
    """
    oid = int(organization_id)
    if oid <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid organization_id")
    if oid == int(user.organization_id):
        return
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not configured (DATABASE_URL).",
        )
    from core.security.org_access import verify_org_membership

    with factory() as session:
        if not verify_org_membership(session, user_id=int(user.id), organization_id=oid):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a member of this organization",
            )


async def get_current_user_optional_org_match(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    organization_id: int | None = None,
) -> CurrentUser:
    """Ensure the user may act in ``organization_id`` when provided (membership, not JWT string match only)."""
    if organization_id is not None:
        ensure_org_membership(user, int(organization_id))
    return user


def require_goal_read_access() -> Callable[..., CurrentUser]:
    """
    Allow owner, admin, manager (goal operators), and viewer (read-only) for AI goal GET routes.

    Blocks staff/worker/customer roles from autonomous goal observability endpoints.
    """

    allowed_names = frozenset({"owner", "admin", "manager", "viewer"})

    async def _dep(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if user.role_name.lower() in allowed_names:
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient role for AI goal read access",
        )

    return _dep


def require_autonomy_admin_actions() -> Callable[..., CurrentUser]:
    """Pause / resume / cancel autonomous jobs — owners and admins only."""

    async def _dep(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if user.role_name.lower() not in {"owner", "admin"}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Requires owner or admin role",
            )
        return user

    return _dep


def require_autonomy_internal_ops() -> Callable[..., CurrentUser]:
    """Internal autonomy diagnostics — owners and admins only (never expose broadly)."""

    async def _dep(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if user.role_name.lower() not in {"owner", "admin"}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Requires owner or admin for internal autonomy endpoints",
            )
        return user

    return _dep


def require_internal_client_when_production(request: Request) -> None:
    """Optional localhost-only gate for sensitive routes when THIRAMAI_INTERNAL_LOCAL_ONLY=1 (production)."""
    if not is_production_environment():
        return
    raw = (os.getenv("THIRAMAI_INTERNAL_LOCAL_ONLY") or "").strip().lower()
    if raw not in {"1", "true", "yes", "on"}:
        return
    host = (request.client.host if request.client else "") or ""
    allowed = {"127.0.0.1", "::1", "localhost"}
    if host not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Internal endpoint not reachable from this network",
        )


def validate_user_access(user_id: int, organization_id: int) -> bool:
    """
    Guard-layer membership check without a route ``CurrentUser`` (service jobs, scripts, tests).

    Opens a short-lived DB session. Routes should prefer ``ensure_org_membership`` for 403 semantics.
    """
    uid = int(user_id)
    oid = int(organization_id)
    if uid <= 0 or oid <= 0:
        return False
    factory = get_session_factory()
    if factory is None:
        return False
    from core.security.org_access import validate_user_access as validate_user_access_in_session

    with factory() as session:
        return validate_user_access_in_session(session, uid, oid)


def get_db_session(
    user: Annotated[CurrentUser, Depends(get_current_user)],
):
    """
    Tenant-scoped DB dependency for routes/services that need direct Session access.

    Uses ``tenant_session_scope`` so PostgreSQL RLS can enforce ``organization_id`` at DB level.
    """
    with tenant_session_scope(int(user.organization_id)) as session:
        yield session


def get_db(
    user: Annotated[CurrentUser, Depends(get_current_user)],
):
    """
    Backward-compatible alias for legacy routes that import ``get_db``.
    """
    yield from get_db_session(user)
