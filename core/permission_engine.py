"""Permission engine: role-inherited grants with optional Redis cache."""

from __future__ import annotations

import time
from typing import Protocol

from sqlalchemy.exc import ProgrammingError
from sqlalchemy import func, select

from core.database import get_session_factory
from core.db.models import Permission as PermissionRow
from core.db.models import Role, RolePermission
from core.redis_cache import cache_get_json, cache_set_json
from core.rbac import permissions_for_role

_CACHE_TTL_SEC = 300
_LOCAL_CACHE: dict[str, tuple[float, frozenset[str]]] = {}


class PermissionUserLike(Protocol):
    """Small protocol for any authenticated principal object."""

    role_name: str
    organization_id: int


def _cache_key(*, organization_id: int, role_name: str) -> str:
    rn = (role_name or "").strip().lower() or "unknown"
    return f"thiramai:permset:{int(organization_id)}:{rn}"


def _local_get(key: str) -> frozenset[str] | None:
    hit = _LOCAL_CACHE.get(key)
    if not hit:
        return None
    expires_at, payload = hit
    if time.time() > expires_at:
        _LOCAL_CACHE.pop(key, None)
        return None
    return payload


def _local_set(key: str, values: frozenset[str]) -> None:
    _LOCAL_CACHE[key] = (time.time() + _CACHE_TTL_SEC, values)


def _db_permissions_for_role(*, organization_id: int, role_name: str) -> frozenset[str]:
    """
    Resolve role-derived permissions from DB (new m2m + legacy permissions.role_id).
    """
    factory = get_session_factory()
    if factory is None:
        return frozenset()

    with factory() as session:
        role = session.execute(
            select(Role).where(
                Role.organization_id == int(organization_id),
                func.lower(Role.name) == (role_name or "").strip().lower(),
            )
        ).scalar_one_or_none()
        if role is None:
            return frozenset()

        rid = int(role.id)
        out: set[str] = set()

        # Preferred schema: role_permissions -> permissions.name
        try:
            rows = session.execute(
                select(PermissionRow.name)
                .join(RolePermission, RolePermission.permission_id == PermissionRow.id)
                .where(RolePermission.role_id == rid)
            ).all()
            for (name,) in rows:
                n = str(name or "").strip()
                if n:
                    out.add(n)
        except ProgrammingError:
            # Backward compatibility for environments that haven't applied RBAC m2m migration.
            session.rollback()

        # Backward compatibility: legacy permissions role-scoped table.
        legacy = session.execute(
            select(PermissionRow.resource, PermissionRow.action).where(PermissionRow.role_id == rid)
        ).all()
        for resource, action in legacy:
            r = str(resource or "").strip()
            a = str(action or "").strip()
            if r and a:
                out.add(f"{r}.{a}")

        return frozenset(out)


def permissions_for_role_cached(*, organization_id: int, role_name: str) -> frozenset[str]:
    """
    Effective permissions for role in org:
    static built-ins UNION database grants, cached (Redis optional + in-process fallback).
    """
    key = _cache_key(organization_id=organization_id, role_name=role_name)

    local = _local_get(key)
    if local is not None:
        return local

    redis_payload = cache_get_json(key)
    if isinstance(redis_payload, list):
        vals = frozenset(str(x).strip() for x in redis_payload if str(x).strip())
        _local_set(key, vals)
        return vals

    effective = frozenset(permissions_for_role(role_name)) | _db_permissions_for_role(
        organization_id=organization_id,
        role_name=role_name,
    )

    _local_set(key, effective)
    cache_set_json(key, sorted(effective), ttl_sec=_CACHE_TTL_SEC)
    return effective


def has_permission(user: PermissionUserLike, permission_name: str) -> bool:
    """
    Helper requested by product requirements.
    """
    perm = (permission_name or "").strip()
    if not perm:
        return False
    perms = permissions_for_role_cached(
        organization_id=int(user.organization_id),
        role_name=user.role_name,
    )
    return perm in perms


def role_has_permission(*, organization_id: int | None = None, role_name: str, permission_name: str) -> bool:
    """Role-only variant for service-level checks outside request context."""
    perm = (permission_name or "").strip()
    if not perm:
        return False
    if organization_id is None:
        return perm in permissions_for_role(role_name)
    return perm in permissions_for_role_cached(
        organization_id=int(organization_id),
        role_name=role_name,
    )
