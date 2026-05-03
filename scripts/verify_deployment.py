#!/usr/bin/env python3
"""
Post-deployment smoke verification (HTTP health, metrics, auth behavior).

Usage:
    python scripts/verify_deployment.py --url https://app.example.com
    python scripts/verify_deployment.py --url http://127.0.0.1:8000 --skip-tls-verify

Requires httpx (runtime dependency of this project).
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import httpx


@dataclass
class DeploymentVerifier:
    base_url: str
    verify_tls: bool = True
    skip_cors: bool = False
    skip_auth_probe: bool = False
    results: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")

    def _client(self) -> httpx.Client:
        return httpx.Client(verify=self.verify_tls, timeout=httpx.Timeout(15.0, connect=10.0))

    def check(self, name: str, func: Callable[[httpx.Client], tuple[bool, str]]) -> bool:
        print(f"\n>> {name}...")
        try:
            with self._client() as client:
                ok, msg = func(client)
        except Exception as exc:  # noqa: BLE001 — surface all probe failures
            print(f"  [ERROR] {exc}")
            self.results.append({"name": name, "status": "error", "message": str(exc)})
            return False
        if ok:
            print(f"  [PASS] {msg}")
            self.results.append({"name": name, "status": "pass", "message": msg})
            return True
        print(f"  [FAIL] {msg}")
        self.results.append({"name": name, "status": "fail", "message": msg})
        return False

    def check_health_live(self, client: httpx.Client) -> tuple[bool, str]:
        r = client.get(f"{self.base_url}/health/live")
        if r.status_code == 200:
            return True, "liveness OK"
        return False, f"HTTP {r.status_code}"

    def check_health_ready(self, client: httpx.Client) -> tuple[bool, str]:
        r = client.get(f"{self.base_url}/health/ready")
        if r.status_code != 200:
            try:
                detail = r.json()
            except Exception:
                detail = r.text[:200]
            return False, f"HTTP {r.status_code}: {detail!s}"[:500]

        data = r.json()
        if data.get("status") != "ready":
            return False, f"status={data.get('status')!r}"

        checks = data.get("checks") or {}
        bad: list[str] = []
        for name, payload in checks.items():
            if not isinstance(payload, dict):
                continue
            if payload.get("ok") is False:
                bad.append(name)
            if name == "database_pool" and payload.get("status") == "unhealthy":
                bad.append("database_pool:unhealthy")
        if bad:
            return False, "failed: " + ", ".join(sorted(set(bad)))
        return True, "readiness OK"

    def check_health_system(self, client: httpx.Client) -> tuple[bool, str]:
        r = client.get(f"{self.base_url}/health/system")
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        payload = r.json()
        if not isinstance(payload, dict):
            return False, "non-JSON body"
        if payload.get("ok") is False:
            return False, f"system not ok: {payload.get('reason', payload)}"
        stuck = int(payload.get("stuck_running_count") or 0)
        if stuck > 0:
            return False, f"stuck_running_count={stuck}"
        return True, "execution runtime snapshot OK"

    def check_database_pool(self, client: httpx.Client) -> tuple[bool, str]:
        r = client.get(f"{self.base_url}/health/ready")
        if r.status_code != 200:
            return False, "readiness not 200"
        pool = (r.json().get("checks") or {}).get("database_pool") or {}
        if not pool:
            return False, "database_pool missing from checks"
        st = str(pool.get("status") or "")
        if st == "unhealthy":
            return False, f"pool unhealthy: {pool.get('error', pool)}"
        if st == "degraded":
            return True, f"pool degraded (warn): {pool.get('utilization_pct', pool)}"
        return True, f"pool {st}: {pool.get('utilization_pct', '?')}"

    def check_prometheus_metrics(self, client: httpx.Client) -> tuple[bool, str]:
        r = client.get(f"{self.base_url}/metrics")
        if r.status_code != 200:
            return False, f"/metrics HTTP {r.status_code}"
        text = r.text
        if "# HELP" not in text or "# TYPE" not in text:
            return False, "not Prometheus exposition format"
        return True, f"prometheus lines ~ {len(text.splitlines())}"

    def check_health_metrics_json(self, client: httpx.Client) -> tuple[bool, str]:
        r = client.get(f"{self.base_url}/health/metrics")
        if r.status_code != 200:
            return False, f"/health/metrics HTTP {r.status_code}"
        data = r.json()
        if not isinstance(data, dict) or "service" not in data:
            return False, "unexpected JSON shape"
        return True, "in-process HTTP counters JSON OK"

    def check_api_auth(self, client: httpx.Client) -> tuple[bool, str]:
        r = client.get(f"{self.base_url}/auth/me")
        if r.status_code == 401:
            return True, "auth required on GET /auth/me"
        if r.status_code == 403:
            return True, "forbidden without credentials (auth boundary)"
        return False, f"unexpected HTTP {r.status_code}"

    def check_cors(self, client: httpx.Client) -> tuple[bool, str]:
        r = client.request(
            "OPTIONS",
            f"{self.base_url}/health/live",
            headers={
                "Origin": "https://thiramai.co.in",
                "Access-Control-Request-Method": "GET",
            },
        )
        allow = r.headers.get("access-control-allow-origin")
        if not allow:
            return False, "Access-Control-Allow-Origin missing"
        if allow == "*":
            return False, "wildcard CORS (avoid in production with credentials)"
        return True, f"allow-origin={allow!r}"

    def check_security_headers(self, client: httpx.Client) -> tuple[bool, str]:
        r = client.get(f"{self.base_url}/health/live")
        need = ("x-content-type-options", "x-frame-options")
        low = {k.lower(): v for k, v in r.headers.items()}
        missing = [h for h in need if h not in low]
        if missing:
            return False, "missing: " + ", ".join(missing)
        return True, "nosniff + frame deny present"

    def check_response_time(self, client: httpx.Client) -> tuple[bool, str]:
        t0 = time.perf_counter()
        r = client.get(f"{self.base_url}/health/live")
        ms = (time.perf_counter() - t0) * 1000
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        if ms > 2000:
            return False, f"slow: {ms:.0f}ms"
        return True, f"{ms:.0f}ms"

    def run_all_checks(self) -> bool:
        print("=" * 72)
        print(f"DEPLOYMENT VERIFICATION: {self.base_url}")
        print(f"UTC: {datetime.now(timezone.utc).isoformat()}")
        print("=" * 72)

        specs: list[tuple[str, Callable[[httpx.Client], tuple[bool, str]]]] = [
            ("Health: liveness", self.check_health_live),
            ("Health: readiness", self.check_health_ready),
            ("Health: system", self.check_health_system),
            ("Database pool (from ready)", self.check_database_pool),
            ("Metrics: Prometheus /metrics", self.check_prometheus_metrics),
            ("Metrics: JSON /health/metrics", self.check_health_metrics_json),
            ("Response time (live)", self.check_response_time),
            ("Security headers (live)", self.check_security_headers),
        ]
        if not self.skip_auth_probe:
            specs.append(("Auth: GET /auth/me unauthenticated", self.check_api_auth))
        if not self.skip_cors:
            specs.append(("CORS preflight", self.check_cors))

        all_ok = True
        for name, fn in specs:
            if not self.check(name, fn):
                all_ok = False

        print("\n" + "=" * 72)
        passed = sum(1 for x in self.results if x["status"] == "pass")
        failed = sum(1 for x in self.results if x["status"] == "fail")
        errors = sum(1 for x in self.results if x["status"] == "error")
        print(f"SUMMARY: pass={passed} fail={failed} error={errors}")
        print("=" * 72)
        return all_ok


def main() -> None:
    p = argparse.ArgumentParser(description="Verify a deployed THIRAMAI API instance.")
    p.add_argument("--url", required=True, help="API base URL (e.g. https://api.example.com)")
    p.add_argument(
        "--skip-tls-verify",
        action="store_true",
        help="Disable TLS certificate verification (local / staging only).",
    )
    p.add_argument(
        "--skip-cors",
        action="store_true",
        help="Skip OPTIONS CORS probe (use if edge strips CORS on probes).",
    )
    p.add_argument(
        "--skip-auth-probe",
        action="store_true",
        help="Skip GET /auth/me probe.",
    )
    args = p.parse_args()

    v = DeploymentVerifier(
        base_url=args.url,
        verify_tls=not args.skip_tls_verify,
        skip_cors=args.skip_cors,
        skip_auth_probe=args.skip_auth_probe,
    )
    ok = v.run_all_checks()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
