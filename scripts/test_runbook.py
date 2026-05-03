#!/usr/bin/env python3
"""
Read-only synthetic checks to verify endpoints referenced in incident runbooks.

Usage:
  set THIRAMAI_RUNBOOK_BASE_URL=https://staging.example.com   # optional
  python scripts/test_runbook.py --list
  python scripts/test_runbook.py --runbook health-smoke
  python scripts/test_runbook.py --all-synthetics

This does NOT simulate incidents or POST emergency actions.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _default_base() -> str:
    return (os.getenv("THIRAMAI_RUNBOOK_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")


def _fetch(url: str, *, method: str = "GET", timeout: float = 20.0) -> tuple[int, str]:
    req = urllib.request.Request(url, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            return int(getattr(resp, "status", 200)), body
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        return int(exc.code), body
    except Exception as exc:
        return -1, f"{type(exc).__name__}: {exc}"


def _step(
    name: str,
    url: str,
    *,
    expected_pattern: str | None = None,
    expected_status: int | None = None,
    status_in: tuple[int, ...] | None = None,
) -> bool:
    code, body = _fetch(url)
    ok = True
    if expected_status is not None and code != expected_status:
        print(f"  FAIL {name}: status {code}, want {expected_status}")
        ok = False
    elif status_in is not None and code not in status_in:
        print(f"  FAIL {name}: status {code}, want one of {status_in}")
        ok = False
    elif expected_pattern is not None and not re.search(expected_pattern, body, re.DOTALL):
        snippet = body[:300].replace("\n", " ")
        print(f"  FAIL {name}: pattern not found in body (snippet: {snippet!r})")
        ok = False
    else:
        print(f"  OK   {name} (HTTP {code})")
    return ok


RUNBOOK_TESTS: dict[str, dict[str, Any]] = {
    "health-smoke": {
        "title": "Core health endpoints (api-availability / outage runbooks)",
        "build_urls": lambda b: [
            (f"{b}/health/live", {"expected_status": 200, "expected_pattern": r"\"status\"\s*:\s*\"alive\""}),
            (f"{b}/health/ready", {"status_in": (200, 503), "expected_pattern": r"\"status\"\s*:\s*\"(ready|not_ready)\""}),
            (f"{b}/health/system", {"status_in": (200, 503), "expected_pattern": r"\b(ok|failure_rate|stuck_running_count)\b"}),
        ],
    },
    "metrics-smoke": {
        "title": "Prometheus text on /metrics",
        "build_urls": lambda b: [
            (f"{b}/metrics", {"expected_status": 200, "expected_pattern": r"thiramai_requests_total|thiramai_request_duration_seconds"}),
        ],
    },
    "trading-halt": {
        "title": "Trading runbook - health only (no auth broker calls)",
        "build_urls": lambda b: [
            (
                f"{b}/health/ready",
                {"status_in": (200, 503), "expected_pattern": r"execution_runtime|database_pool"},
            ),
        ],
    },
    "db-pool-exhaustion": {
        "title": "Pool data present in readiness JSON",
        "build_urls": lambda b: [
            (
                f"{b}/health/ready",
                {"status_in": (200, 503), "expected_pattern": r"database_pool"},
            ),
        ],
    },
}


def test_runbook(name: str, base: str) -> bool:
    spec = RUNBOOK_TESTS.get(name)
    if not spec:
        print(f"Unknown runbook key: {name}", file=sys.stderr)
        return False
    print(f"\n== {spec['title']} ==")
    all_ok = True
    for url, kwargs in spec["build_urls"](base):
        label = url.removeprefix(base + "/")
        if not _step(label, url, **kwargs):
            all_ok = False
    return all_ok


def main() -> None:
    p = argparse.ArgumentParser(description="Runbook read-only synthetic checks")
    p.add_argument("--base-url", default=None, help="Override THIRAMAI_RUNBOOK_BASE_URL")
    p.add_argument("--list", action="store_true", help="List defined synthetics")
    p.add_argument("--runbook", help="Run a single synthetic key")
    p.add_argument("--all-synthetics", action="store_true", help="Run every defined synthetic")
    args = p.parse_args()

    base = (args.base_url or _default_base()).rstrip("/")

    if args.list:
        for k, v in sorted(RUNBOOK_TESTS.items()):
            print(f"{k}: {v['title']}")
        return

    if args.all_synthetics:
        results = {k: test_runbook(k, base) for k in RUNBOOK_TESTS}
        ok = all(results.values())
        print("\nSummary:")
        for k, v in results.items():
            print(f"  {'PASS' if v else 'FAIL'}  {k}")
        raise SystemExit(0 if ok else 1)

    if args.runbook:
        raise SystemExit(0 if test_runbook(args.runbook, base) else 1)

    p.error("Specify --list, --runbook KEY, or --all-synthetics")


if __name__ == "__main__":
    main()
