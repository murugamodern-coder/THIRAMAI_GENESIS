"""Fernet helpers for OAuth tokens stored on ``UserIntegration`` rows."""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet


def _secret_material() -> bytes:
    raw = (
        os.getenv("THIRAMAI_INTEGRATION_FERNET_KEY") or os.getenv("SECRET_KEY") or "dev-unsafe-thiramai-integration"
    ).encode("utf-8")
    return raw


def integration_fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(_secret_material()).digest())
    return Fernet(key)


def encrypt_secret(plain: str | None) -> str | None:
    if not plain:
        return None
    return integration_fernet().encrypt(str(plain).encode("utf-8")).decode("ascii")


def decrypt_secret(blob: str | None) -> str | None:
    if not blob:
        return None
    try:
        return integration_fernet().decrypt(str(blob).encode("ascii")).decode("utf-8")
    except Exception:
        return None
