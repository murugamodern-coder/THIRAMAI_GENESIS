#!/usr/bin/env python3
"""
End-to-end check: login as admin_king, then POST /chat/query with Bearer token.

Requires a running API (e.g. python -m uvicorn main:app --reload) and GROQ_API_KEY + TAVILY_API_KEY on the server.
"""

from __future__ import annotations

import json
import os
import sys

import httpx

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_URL = (os.getenv("TEST_AI_CHAT_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
# Same identity as scripts/create_admin.py (OAuth2 username is the email).
LOGIN_USERNAME = os.getenv("TEST_AI_CHAT_EMAIL") or "admin_king@thiramai.empire"
LOGIN_PASSWORD = os.getenv("TEST_AI_CHAT_PASSWORD") or "Thiramai@2026"
MESSAGE = (
    "Hello AI Manager, give me a quick status report of Thiramai Empire."
)


def main() -> int:
    login_url = f"{BASE_URL}/auth/login"
    chat_url = f"{BASE_URL}/chat/query"

    with httpx.Client(timeout=120.0) as client:
        print(f"POST {login_url} (OAuth2 form: username=email, password=...)")
        login_r = client.post(
            login_url,
            data={
                "username": LOGIN_USERNAME,
                "password": LOGIN_PASSWORD,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        print(f"Login status: {login_r.status_code}")
        if login_r.status_code != 200:
            print(login_r.text, file=sys.stderr)
            return 1

        try:
            token = login_r.json().get("access_token")
        except json.JSONDecodeError:
            print(login_r.text, file=sys.stderr)
            return 1
        if not token:
            print("No access_token in login response.", file=sys.stderr)
            return 1

        print(f"\nPOST {chat_url}")
        print(f"Message: {MESSAGE!r}\n")
        chat_r = client.post(
            chat_url,
            json={"message": MESSAGE},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        print(f"Chat status: {chat_r.status_code}")

    try:
        body = chat_r.json()
    except json.JSONDecodeError:
        print(chat_r.text)
        return 1 if chat_r.status_code >= 400 else 0

    if chat_r.status_code != 200:
        print(json.dumps(body, indent=2))
        return 1

    narrative = body.get("narrative") or body.get("response") or ""
    print("--- AI narrative (orchestrator + context) ---")
    print(narrative)
    print("--- structured action_intent ---")
    print(json.dumps(body.get("action_intent"), indent=2))
    qa = body.get("quick_actions")
    if qa:
        print("--- quick_actions ---")
        print(json.dumps(qa, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
