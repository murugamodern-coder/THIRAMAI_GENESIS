"""
Opaque refresh tokens (hash at rest). Used by ``POST /auth/refresh``.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.models import RefreshToken, Role, User, UserOrganizationMembership
from services.membership_service import first_active_membership


def _hash_plain(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def refresh_token_ttl_days() -> int:
    try:
        return max(1, int((os.getenv("JWT_REFRESH_EXPIRE_DAYS") or "30").strip()))
    except ValueError:
        return 30


def issue_refresh_token(session: Session, *, user_id: int) -> str:
    """Insert a new refresh row; return the **plaintext** token once (caller returns to client)."""
    uid = int(user_id)
    plain = secrets.token_urlsafe(48)
    th = _hash_plain(plain)
    exp = datetime.now(timezone.utc) + timedelta(days=refresh_token_ttl_days())
    session.add(
        RefreshToken(
            user_id=uid,
            token_hash=th,
            expires_at=exp,
        )
    )
    session.flush()
    return plain


def revoke_refresh_token(session: Session, *, plain: str) -> RefreshToken | None:
    """Mark the token row revoked if it matches and is currently active."""
    th = _hash_plain(plain.strip())
    row = session.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == th,
            RefreshToken.revoked_at.is_(None),
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    now = datetime.now(timezone.utc)
    if row.expires_at <= now:
        return None
    row.revoked_at = now
    session.flush()
    return row


def load_valid_refresh_row(session: Session, *, plain: str) -> RefreshToken | None:
    th = _hash_plain(plain.strip())
    now = datetime.now(timezone.utc)
    return session.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == th,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
    ).scalar_one_or_none()


def membership_context_for_refresh(session: Session, *, user_id: int) -> tuple[User, UserOrganizationMembership, Role] | None:
    """Same membership pick as login: first active membership + role."""
    u = session.get(User, int(user_id))
    if u is None or not u.is_active:
        return None
    mem = first_active_membership(session, int(u.id))
    if mem is None:
        return None
    role = session.get(Role, int(mem.role_id))
    if role is None:
        return None
    return u, mem, role
