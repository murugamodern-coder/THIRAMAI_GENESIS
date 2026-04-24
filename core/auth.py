"""
JWT access tokens (HS256) and bcrypt password hashing for THIRAMAI.

Environment (roadmap):
  SECRET_KEY  — signing secret (falls back to JWT_SECRET_KEY for older .env files)
  ALGORITHM   — e.g. HS256 (falls back to JWT_ALGORITHM)

Optional:
  JWT_ACCESS_EXPIRE_MINUTES — access token lifetime (default **1440** minutes / 24 h if unset).
  JWT_EXPIRE_MINUTES — legacy alias for access TTL when JWT_ACCESS_EXPIRE_MINUTES unset.
  JWT_REFRESH_EXPIRE_DAYS — refresh token storage lifetime (default 30); see ``refresh_tokens`` table.
  JWT_ISSUER — if set, embedded as ``iss`` and validated on decode.
  JWT_AUDIENCE — if set, embedded as ``aud`` and validated on decode.
  JWT_TOKEN_VERSION — integer claim ``tv`` (default **1**) for future mass revocation / rotation.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTError


def _password_bytes(plain_password: str) -> bytes:
    """UTF-8 bytes truncated to bcrypt's 72-byte input limit."""
    raw = plain_password.encode("utf-8")
    return raw[:72] if len(raw) > 72 else raw


def _secret_key() -> str:
    """Resolve signing secret: SECRET_KEY, JWT_SECRET_KEY, or JWT_SECRET (alias)."""
    return (
        os.getenv("SECRET_KEY")
        or os.getenv("JWT_SECRET_KEY")
        or os.getenv("JWT_SECRET")
        or ""
    ).strip()


def _algorithm() -> str:
    """Resolve JWT alg with safe default and optional asymmetric override."""
    alg = (os.getenv("ALGORITHM") or os.getenv("JWT_ALGORITHM") or "HS256").strip().upper()
    if not alg:
        alg = "HS256"
    allow_asymmetric = (os.getenv("THIRAMAI_ALLOW_ASYMMETRIC_JWT") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not allow_asymmetric and not alg.startswith("HS"):
        raise RuntimeError(
            f"JWT algorithm '{alg}' is blocked by policy. "
            "Use HS256/HS384/HS512 or set THIRAMAI_ALLOW_ASYMMETRIC_JWT=1 with security review."
        )
    return alg


def _token_version() -> int:
    raw = (os.getenv("JWT_TOKEN_VERSION") or "1").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def _jwt_issuer() -> str | None:
    v = (os.getenv("JWT_ISSUER") or "").strip()
    return v or None


def _jwt_audience() -> str | None:
    v = (os.getenv("JWT_AUDIENCE") or "").strip()
    return v or None


def _access_expire_minutes() -> int:
    """Access token TTL in minutes (short-lived; pair with refresh token in Phase 8)."""
    raw = (os.getenv("JWT_ACCESS_EXPIRE_MINUTES") or "").strip()
    if raw:
        try:
            return max(5, int(raw))
        except ValueError:
            pass
    leg = (os.getenv("JWT_EXPIRE_MINUTES") or "").strip()
    if leg:
        try:
            return max(5, int(leg))
        except ValueError:
            pass
    return 1440


def access_token_ttl_seconds() -> int:
    """Wall-clock seconds for access JWT ``exp`` (for API ``expires_in``)."""
    try:
        return int(_access_expire_minutes() * 60)
    except Exception:
        return 86400


def hash_password(plain_password: str) -> str:
    """
    Hash a plaintext password with bcrypt for storage in users.password_hash.

    Bcrypt limits input to ~72 bytes; longer UTF-8 passwords are truncated here.
    """
    return bcrypt.hashpw(_password_bytes(plain_password), bcrypt.gensalt()).decode("ascii")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """
    Verify plaintext against the stored bcrypt hash.

    Returns False on mismatch, missing hash, or invalid hash format.
    """
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(
            _password_bytes(plain_password),
            password_hash.encode("ascii"),
        )
    except (ValueError, TypeError):
        return False


def create_access_token(
    *,
    sub_user_id: int,
    org_id: int,
    role_name: str,
    active_org_id: int | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """
    Issue a signed JWT whose payload includes sub, org_id, active_org_id, role, exp, and iat.

    - ``org_id`` / ``active_org_id``: active tenant for this session (same value when ``active_org_id`` omitted).
    - ``role``: role name for that membership.

    Raises RuntimeError if SECRET_KEY / JWT_SECRET_KEY is not set.
    """
    secret = _secret_key()
    if not secret:
        raise RuntimeError(
            "SECRET_KEY (or JWT_SECRET_KEY) is not set. Add it to `.env` before issuing tokens."
        )
    now = datetime.now(timezone.utc)
    delta = expires_delta if expires_delta is not None else timedelta(minutes=_access_expire_minutes())
    active = int(active_org_id) if active_org_id is not None else int(org_id)
    payload: dict[str, Any] = {
        "sub": str(sub_user_id),
        "org_id": str(active),
        "active_org_id": str(active),
        "role": role_name,
        "tv": _token_version(),
        "exp": now + delta,
        "iat": now,
    }
    iss = _jwt_issuer()
    if iss:
        payload["iss"] = iss
    aud = _jwt_audience()
    if aud:
        payload["aud"] = aud
    return jwt.encode(payload, secret, algorithm=_algorithm())


def get_current_user(token: str) -> dict[str, Any]:
    """
    Decode and validate a Bearer token; return the JWT payload (claims) dict.

    Handles:
      - ExpiredSignatureError — token past exp
      - JWTError — bad signature, malformed token, wrong algorithm, missing secret, etc.

    On success returns claims including at least sub, org_id, role when issued by create_access_token.
    Re-raises the same exception types after decode failure so API layers can map to 401.
    """
    stripped = (token or "").strip()
    if not stripped:
        raise JWTError("missing token")

    secret = _secret_key()
    if not secret:
        raise JWTError("SECRET_KEY (or JWT_SECRET_KEY) is not set")

    aud = _jwt_audience()
    iss = _jwt_issuer()
    try:
        return jwt.decode(
            stripped,
            secret,
            algorithms=[_algorithm()],
            audience=aud,
            issuer=iss,
        )
    except ExpiredSignatureError:
        # Explicit branch: expired tokens are common; callers may treat differently if needed.
        raise
    except JWTError:
        raise


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Back-compat alias for get_current_user (same decode path, same errors).

    Prefer get_current_user in new code.
    """
    return get_current_user(token)


def runtime_validate_auth_crypto() -> tuple[bool, str]:
    """
    Runtime validation guard for JWT crypto wiring.

    Performs a local issue/decode round trip using current env policy to fail fast
    when an incompatible cryptography/jose runtime is present.
    """
    try:
        tok = create_access_token(sub_user_id=1, org_id=1, role_name="owner")
        claims = get_current_user(tok)
        if str(claims.get("sub")) != "1":
            return False, "jwt_roundtrip_claim_mismatch"
        return True, f"jwt_roundtrip_ok alg={_algorithm()}"
    except Exception as exc:
        return False, f"jwt_roundtrip_failed: {exc}"


def token_subject_user_id(claims: dict[str, Any]) -> int:
    """Parse integer user id from the standard `sub` claim."""
    sub = claims.get("sub")
    if sub is None:
        raise JWTError("missing sub")
    return int(str(sub))
