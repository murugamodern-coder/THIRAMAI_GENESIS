#!/usr/bin/env python3
"""
Register the first tenant admin via POST /auth/register.

The API expects email + password + organization_name. The first user is always Owner (role "owner").
We map logical username "admin_king" to a valid EmailStr for login (OAuth2 form: username=that email).
"""

from __future__ import annotations

import json
import os
import sys

import httpx

BASE_URL = (os.getenv("CREATE_ADMIN_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
# Logical username -> API requires email
USERNAME = "admin_king"
EMAIL = f"{USERNAME}@thiramai.empire"
PASSWORD = "Thiramai@2026"
ORGANIZATION_NAME = "Thiramai_Empire"
# Role: register endpoint always creates Owner; no field in JSON.


def main() -> int:
    payload = {
        "email": EMAIL,
        "password": PASSWORD,
        "organization_name": ORGANIZATION_NAME,
    }
    url = f"{BASE_URL}/auth/register"
    print(f"POST {url}")
    print("Payload (password redacted):", json.dumps({**payload, "password": "***"}, indent=2))
    try:
        r = httpx.post(url, json=payload, timeout=60.0)
    except httpx.RequestError as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1

    print(f"\nStatus: {r.status_code}")
    try:
        body = r.json()
        print(json.dumps(body, indent=2))
    except json.JSONDecodeError:
        print(r.text)

    if r.status_code == 201:
        print("\nOK: Admin (Owner) user created. Log in with email:", EMAIL)
        return 0
    if r.status_code == 409:
        print("\nNote: Email already registered - user likely exists already.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
