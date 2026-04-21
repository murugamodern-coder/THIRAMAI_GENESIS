"""Resolve broker credentials with per-user runtime_config overlay over process env."""

from __future__ import annotations

import os

from services.security.vault_service import getenv_for_user


def fyers_triplet(user_id: int) -> tuple[str, str, str]:
    cid = getenv_for_user(user_id, "FYERS_CLIENT_ID") or ""
    secret = (
        getenv_for_user(user_id, "FYERS_SECRET_KEY")
        or os.getenv("FYERS_SECRET_KEY")
        or os.getenv("FYERS_SECRET")
        or ""
    ).strip()
    token = getenv_for_user(user_id, "FYERS_ACCESS_TOKEN") or ""
    return cid.strip(), secret, token.strip()


def kite_triplet(user_id: int) -> tuple[str, str, str]:
    key = getenv_for_user(user_id, "KITE_API_KEY") or ""
    sec = getenv_for_user(user_id, "KITE_API_SECRET") or ""
    tok = getenv_for_user(user_id, "KITE_ACCESS_TOKEN") or ""
    return key.strip(), sec.strip(), tok.strip()


def fyers_configured_for_user(user_id: int) -> bool:
    c, s, t = fyers_triplet(user_id)
    return bool(c and s and t)


def kite_configured_for_user(user_id: int) -> bool:
    k, s, t = kite_triplet(user_id)
    return bool(k and s and t)


def broker_provider_for_user(user_id: int) -> str:
    return (
        getenv_for_user(user_id, "THIRAMAI_BROKER_PROVIDER")
        or os.getenv("THIRAMAI_BROKER_PROVIDER")
        or "fyers"
    ).strip().lower()
