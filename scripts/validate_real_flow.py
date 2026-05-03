#!/usr/bin/env python3
"""
Quick HTTP + import smoke checks against a running API (default http://127.0.0.1:8000).

Does not mutate the database. For a seeded user/org, use ``scripts/setup_test_data.py``.

Usage:
    python scripts/validate_real_flow.py
    python scripts/validate_real_flow.py https://api.example.com
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx


def main() -> int:
    p = argparse.ArgumentParser(description="Validate Thiramai API reachability and core imports.")
    p.add_argument("base_url", nargs="?", default="http://127.0.0.1:8000", help="API base URL")
    p.add_argument("--skip-tls-verify", action="store_true", help="Disable TLS verify (local only)")
    args = p.parse_args()
    base = args.base_url.rstrip("/")
    verify = not args.skip_tls_verify
    results: list[bool] = []

    print("=" * 60)
    print("REAL FLOW VALIDATION (smoke)")
    print("=" * 60)

    print("\n>> GET /health/live ...")
    try:
        with httpx.Client(timeout=10.0, verify=verify) as c:
            r = c.get(f"{base}/health/live")
        ok = r.status_code == 200
        print(f"  [{'PASS' if ok else 'FAIL'}] HTTP {r.status_code}")
        results.append(ok)
    except Exception as exc:
        print(f"  [FAIL] {exc}")
        results.append(False)
        return 1

    print("\n>> POST /auth/login (expect 401 wrong password) ...")
    try:
        with httpx.Client(timeout=10.0, verify=verify) as c:
            r = c.post(
                f"{base}/auth/login",
                data={"username": "no_such_user_ever@local.invalid", "password": "wrong"},
            )
        ok = r.status_code in (401, 422)
        print(f"  [{'PASS' if ok else 'FAIL'}] HTTP {r.status_code}")
        results.append(ok)
    except Exception as exc:
        print(f"  [FAIL] {exc}")
        results.append(False)

    print("\n>> Import PolicyEngine ...")
    try:
        from services.policy_engine import PolicyEngine

        pe = PolicyEngine()
        assert hasattr(pe, "decide") and callable(pe.decide)
        print("  [PASS] PolicyEngine initialized")
        results.append(True)
    except Exception as exc:
        print(f"  [FAIL] {exc}")
        results.append(False)

    print("\n>> Import DecisionRouter ...")
    try:
        from services.decision_router import DecisionRouter

        dr = DecisionRouter()
        assert hasattr(dr, "route") and callable(dr.route)
        print("  [PASS] DecisionRouter initialized")
        results.append(True)
    except Exception as exc:
        print(f"  [FAIL] {exc}")
        results.append(False)

    print("\n>> Import ORM models ...")
    try:
        from core.db.models import AiDecision, LearningLog, User

        _ = (User, AiDecision, LearningLog)
        print("  [PASS] core.db.models")
        results.append(True)
    except Exception as exc:
        print(f"  [FAIL] {exc}")
        results.append(False)

    passed = sum(1 for x in results if x)
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{len(results)} checks passed")
    print("=" * 60)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
