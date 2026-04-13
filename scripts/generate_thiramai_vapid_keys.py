#!/usr/bin/env python3
"""
Generate VAPID keys for Web Push. Requires: pip install cryptography

Usage:
  python scripts/generate_thiramai_vapid_keys.py

Copy printed lines into .env (use a real mailto: or https: subject for production).
"""

from __future__ import annotations

import base64

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def main() -> None:
    private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
    priv_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pub = private_key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    pub_b64u = base64.urlsafe_b64encode(pub).decode().rstrip("=")
    print("THIRAMAI_VAPID_PUBLIC_KEY=" + pub_b64u)
    print('THIRAMAI_VAPID_PRIVATE_KEY="' + priv_pem.replace(chr(10), "\\n") + '"')
    print("THIRAMAI_VAPID_SUBJECT=mailto:you@yourdomain.com")
    print("# Optional: UTC hour (0-23) to send daily brief push (default ~7:30 IST when set to 2)")
    print("# THIRAMAI_PUSH_DAILY_BRIEF_HOUR_UTC=2")


if __name__ == "__main__":
    main()
