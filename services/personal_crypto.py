"""
Application-layer encryption for Life OS private fields (Fernet + PBKDF2-HMAC-SHA256).

We store only **salt** and **SHA-256(raw_derived_key)** as verifier — never the passphrase or Fernet key.
Decrypting requires the user passphrase plus the per-user salt loaded from the DB.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_PBKDF2_ITERATIONS = 390_000

# Fixed salt for deriving a **server** Fernet key from ``VAULT_PASSPHRASE`` (Life OS vault migration / enc_notes).
# Not interchangeable with per-user PBKDF2 rows in ``user_personal_crypto``.
_SERVER_VAULT_KDF_SALT = b"thiramai-genesis-v1-server-vault"


def new_salt() -> bytes:
    return os.urandom(16)


def derive_raw_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
        backend=default_backend(),
    )
    return kdf.derive((passphrase or "").encode("utf-8"))


def verifier_hash(raw_key: bytes) -> str:
    return hashlib.sha256(raw_key).hexdigest()


def verify_raw_key(raw_key: bytes, expected_verifier_hex: str) -> bool:
    try:
        got = verifier_hash(raw_key)
        return secrets.compare_digest(got, (expected_verifier_hex or "").strip().lower())
    except Exception:
        return False


def fernet_from_raw(raw_key: bytes) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(raw_key))


def encrypt_utf8(fernet: Fernet, plaintext: str) -> bytes:
    return fernet.encrypt((plaintext or "").encode("utf-8"))


def decrypt_utf8(fernet: Fernet, token: bytes) -> Optional[str]:
    try:
        return fernet.decrypt(token).decode("utf-8")
    except InvalidToken:
        return None


def fernet_from_vault_passphrase(passphrase: str) -> Fernet:
    """
    Derive a Fernet instance from a long-lived env passphrase (``VAULT_PASSPHRASE``).

    Uses PBKDF2 with a fixed application salt — distinct from user-specific vault keys.
    """
    raw = derive_raw_key((passphrase or "").strip(), _SERVER_VAULT_KDF_SALT)
    return fernet_from_raw(raw)
