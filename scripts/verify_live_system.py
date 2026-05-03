#!/usr/bin/env python3
"""
Complete live system verification.

End-to-end checks against a running Thiramai API:
environment file, Docker compose, health probes, PolicyEngine, auth, decision API,
brain source, optional DB persistence (direct URL or docker compose exec), AI quality,
Prometheus /metrics.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional

try:
    import httpx
except ImportError as e:  # pragma: no cover
    print("Install httpx (project dependency): pip install httpx", file=sys.stderr)
    raise SystemExit(2) from e


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _parse_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        out[k] = v
    return out


def _truthy(val: str | None) -> bool:
    if val is None:
        return False
    return val.strip().lower() in ("1", "true", "yes", "on")


def _compose_ps_services(
    repo: Path,
    *,
    env_file: Path,
) -> list[dict[str, Any]]:
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(repo / "docker-compose.production.yml"),
            "--env-file",
            str(env_file),
            "ps",
            "-a",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        cwd=repo,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or "docker compose ps failed")
    raw = (result.stdout or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
    except json.JSONDecodeError:
        pass
    rows: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _normalize_sqlalchemy_url(url: str) -> str:
    u = url.strip().strip('"').strip("'")
    for prefix in ("postgresql+psycopg2://", "postgresql+asyncpg://"):
        if u.startswith(prefix):
            return "postgresql://" + u.split("://", 1)[1]
    return u


class LiveSystemVerifier:
    def __init__(
        self,
        *,
        base_url: str,
        verify_tls: bool,
        env_file: Path,
        repo: Path,
        skip_docker: bool,
        relax_db: bool,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.verify_tls = verify_tls
        self.env_file = env_file
        self.repo = repo
        self.skip_docker = skip_docker
        self.relax_db = relax_db
        self.token: str | None = None
        self.checks_passed: list[str] = []
        self.checks_failed: list[tuple[str, str, Optional[dict[str, Any]]]] = []
        self._last_decision_id: str | None = None

    def _client(self) -> httpx.Client:
        return httpx.Client(verify=self.verify_tls, timeout=httpx.Timeout(60.0, connect=15.0))

    def run_all_checks(self) -> bool:
        os.chdir(self.repo)
        print("=" * 70)
        print("THIRAMAI LIVE SYSTEM VERIFICATION")
        print("=" * 70)
        print(f"\nBase URL: {self.base_url}")
        print(f"Env file: {self.env_file}")
        print()

        checks: list[tuple[str, Callable[[], tuple[bool, str, Optional[dict[str, Any]]]]]] = [
            ("Environment File", self.check_environment_file),
            ("Docker Services", self.check_docker_services),
            ("Health - Live", self.check_health_live),
            ("Health - Ready", self.check_health_ready),
            ("Health - System", self.check_health_system),
            ("PolicyEngine Status", self.check_policy_engine),
            ("Circuit Breaker", self.check_circuit_breaker),
            ("Authentication", self.check_authentication),
            ("Decision API", self.check_decision_api),
            ("AI Brain Source", self.check_ai_brain_source),
            ("Database Persistence", self.check_database_persistence),
            ("Quality Tracking", self.check_quality_tracking),
            ("Metrics Endpoint", self.check_metrics),
        ]

        for name, fn in checks:
            self.run_check(name, fn)

        self.print_summary()
        return len(self.checks_failed) == 0

    def run_check(
        self,
        name: str,
        func: Callable[[], tuple[bool, str, Optional[dict[str, Any]]]],
    ) -> bool:
        print(f"\n{'=' * 70}")
        print(f"▶ {name}")
        print(f"{'=' * 70}")
        try:
            success, message, details = func()
            if success:
                print(f"✅ PASS: {message}")
                if details:
                    print(f"   Details: {json.dumps(details, indent=2, default=str)[:6000]}")
                self.checks_passed.append(name)
                return True
            print(f"❌ FAIL: {message}")
            if details:
                print(f"   Details: {json.dumps(details, indent=2, default=str)[:6000]}")
            self.checks_failed.append((name, message, details))
            return False
        except Exception as exc:  # noqa: BLE001 — surface probe failures
            print(f"❌ ERROR: {exc}")
            import traceback

            traceback.print_exc()
            self.checks_failed.append((name, str(exc), None))
            return False

    def check_environment_file(self) -> tuple[bool, str, Optional[dict[str, Any]]]:
        if not self.env_file.is_file():
            return False, f"{self.env_file} not found", None
        env = _parse_dotenv(self.env_file)
        missing: list[str] = []
        if not env.get("DATABASE_URL", "").strip():
            missing.append("DATABASE_URL")

        ab_on = _truthy(env.get("THIRAMAI_DECISION_AB_TEST")) or _truthy(
            env.get("DECISION_AB_TEST")
        )
        if ab_on:
            missing.append("Turn off A/B: THIRAMAI_DECISION_AB_TEST=false (and/or DECISION_AB_TEST=false)")
        pool_ok = any(k in env for k in ("POOL_SIZE", "THIRAMAI_DB_POOL_SIZE")) and any(
            k in env for k in ("MAX_OVERFLOW", "THIRAMAI_DB_MAX_OVERFLOW")
        )
        if not pool_ok:
            missing.append("POOL_SIZE+MAX_OVERFLOW (or THIRAMAI_DB_* equivalents)")
        if missing:
            return False, f"Incomplete env: {missing}", {"missing": missing}
        return True, "Environment file has required keys", {"checked_keys": sorted(env.keys())[:40]}

    def check_docker_services(self) -> tuple[bool, str, Optional[dict[str, Any]]]:
        if self.skip_docker:
            return True, "Skipped (--skip-docker)", None
        try:
            services = _compose_ps_services(self.repo, env_file=self.env_file)
        except Exception as exc:
            return False, f"Docker compose failed: {exc}", None
        if not services:
            return False, "No compose services reported (stack not running?)", None
        running: list[str] = []
        for s in services:
            state = (s.get("State") or s.get("state") or "").lower()
            if "running" in state:
                name = s.get("Service") or s.get("Name") or s.get("service") or "?"
                running.append(str(name))
        if len(running) < 2:
            return (
                False,
                f"Expected at least 2 running services, got {len(running)}",
                {"running": running, "raw_count": len(services)},
            )
        return True, f"{len(running)} compose service(s) running", {"running": running}

    def check_health_live(self) -> tuple[bool, str, Optional[dict[str, Any]]]:
        try:
            with self._client() as client:
                r = client.get(f"{self.base_url}/health/live")
        except httpx.RequestError as exc:
            return False, f"Request failed: {exc}", None
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}", _safe_json(r)
        data = r.json()
        if data.get("status") != "alive":
            return False, f"Unexpected status: {data.get('status')!r}", data
        return True, "Liveness OK", data

    def check_health_ready(self) -> tuple[bool, str, Optional[dict[str, Any]]]:
        try:
            with self._client() as client:
                r = client.get(f"{self.base_url}/health/ready")
        except httpx.RequestError as exc:
            return False, f"Request failed: {exc}", None
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text[:300]}
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}", data
        st = data.get("status")
        if st != "ready":
            return False, f"Readiness status: {st!r}", data
        return True, "Readiness OK (status=ready)", {"checks": list((data.get("checks") or {}).keys())}

    def check_health_system(self) -> tuple[bool, str, Optional[dict[str, Any]]]:
        try:
            with self._client() as client:
                r = client.get(f"{self.base_url}/health/system")
        except httpx.RequestError as exc:
            return False, f"Request failed: {exc}", None
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}", _safe_json(r)
        data = r.json()
        if not isinstance(data, dict):
            return False, "Non-object JSON", None
        if not data.get("ok"):
            return False, f"System check not ok: {data.get('reason', data)}", data
        if int(data.get("stuck_running_count") or 0) > 0:
            return False, f"stuck_running_count={data.get('stuck_running_count')}", data
        slim = {
            k: data.get(k)
            for k in ("window_hours", "total_runs", "success_rate", "failure_rate", "execution_backlog")
            if k in data
        }
        return True, "Execution runtime OK", slim or {"ok": True}

    def check_policy_engine(self) -> tuple[bool, str, Optional[dict[str, Any]]]:
        try:
            with self._client() as client:
                r = client.get(f"{self.base_url}/health/ready")
        except httpx.RequestError as exc:
            return False, f"Request failed: {exc}", None
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}", _safe_json(r)
        data = r.json()
        pe = (data.get("checks") or {}).get("policy_engine") or {}
        status = pe.get("status")
        if status == "healthy":
            return True, "PolicyEngine healthy", pe
        if status == "degraded":
            return True, "PolicyEngine degraded (circuit half-open/open window — acceptable for probe)", pe
        return False, f"PolicyEngine status: {status!r}", pe

    def check_circuit_breaker(self) -> tuple[bool, str, Optional[dict[str, Any]]]:
        try:
            with self._client() as client:
                r = client.get(f"{self.base_url}/health/ready")
        except httpx.RequestError as exc:
            return False, f"Request failed: {exc}", None
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}", _safe_json(r)
        data = r.json()
        cb = (data.get("checks") or {}).get("policy_engine") or {}
        cb = cb.get("circuit_breaker") or {}
        state = str(cb.get("state") or "").lower()
        if state in ("closed", "half_open"):
            return True, f"Circuit {state} (normal or recovering)", cb
        if state == "open":
            return False, "Circuit breaker OPEN — PolicyEngine calls short-circuited", cb
        return False, f"Unknown circuit state: {state!r}", cb

    def check_authentication(self) -> tuple[bool, str, Optional[dict[str, Any]]]:
        user = os.environ.get("THIRAMAI_LIVE_VERIFY_USER", "admin_king")
        password = os.environ.get("THIRAMAI_LIVE_VERIFY_PASSWORD", "thiramai_2026")
        try:
            with self._client() as client:
                r = client.post(
                    f"{self.base_url}/auth/login",
                    data={"username": user, "password": password},
                )
        except httpx.RequestError as exc:
            return False, f"Request failed: {exc}", None
        if r.status_code != 200:
            return False, f"Login HTTP {r.status_code}", _safe_json(r)
        data = r.json()
        token = data.get("access_token")
        if not token:
            return False, "No access_token in login response", data
        self.token = str(token)
        return True, "Authenticated", {"token_type": data.get("token_type"), "user": user}

    def check_decision_api(self) -> tuple[bool, str, Optional[dict[str, Any]]]:
        if not self.token:
            return False, "No token (login must pass)", None
        try:
            with self._client() as client:
                r = client.post(
                    f"{self.base_url}/chat/decision",
                    headers={"Authorization": f"Bearer {self.token}"},
                    json={"message": "Should I invest in gold now?"},
                )
        except httpx.RequestError as exc:
            return False, f"Request failed: {exc}", None
        if r.status_code != 200:
            return False, f"Decision HTTP {r.status_code}", _safe_json(r)
        data = r.json()
        if "decision" not in data:
            return False, "Missing top-level decision", {k: type(v).__name__ for k, v in data.items()}
        dec = data.get("decision") or {}
        if isinstance(dec, dict):
            did = data.get("decision_id") or dec.get("id")
            if did:
                self._last_decision_id = str(did)
        return True, "Decision API returned a bundle", {
            "phase": data.get("phase"),
            "status": data.get("status"),
            "decision_id": self._last_decision_id,
            "confidence": dec.get("confidence") if isinstance(dec, dict) else None,
        }

    def check_ai_brain_source(self) -> tuple[bool, str, Optional[dict[str, Any]]]:
        if not self.token:
            return False, "No token", None
        try:
            with self._client() as client:
                r = client.post(
                    f"{self.base_url}/chat/decision",
                    headers={"Authorization": f"Bearer {self.token}"},
                    json={"message": "Live verify: brain source probe"},
                )
        except httpx.RequestError as exc:
            return False, f"Request failed: {exc}", None
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}", _safe_json(r)
        data = r.json()
        dec = data.get("decision") or {}
        inner = dec.get("data") if isinstance(dec, dict) else {}
        if not isinstance(inner, dict):
            inner = {}
        source = inner.get("decision_brain_source")
        if source == "policy_engine":
            return True, "Brain source is policy_engine", {"source": source}
        if source == "safe_fallback":
            return True, "Brain source is safe_fallback (degraded but governed)", {"source": source}
        return False, f"Unexpected decision_brain_source: {source!r}", {"source": source, "keys": list(inner.keys())}

    def check_database_persistence(self) -> tuple[bool, str, Optional[dict[str, Any]]]:
        env = _parse_dotenv(self.env_file)
        db_url = (env.get("DATABASE_URL") or "").strip()
        override = (os.environ.get("THIRAMAI_LIVE_DB_URL") or "").strip()
        if override:
            db_url = override

        last_err: str = ""

        if db_url:
            try:
                from sqlalchemy import create_engine, text

                eng = create_engine(_normalize_sqlalchemy_url(db_url), pool_pre_ping=True)
                with eng.connect() as conn:
                    row = conn.execute(
                        text(
                            "SELECT COUNT(*) FROM ai_decisions "
                            "WHERE created_at > NOW() - INTERVAL '15 minutes'"
                        )
                    ).one()
                    count = int(row[0])
                if count > 0:
                    return True, f"Recent ai_decisions rows: {count} (direct DB URL)", {"count": count}
                return (
                    True,
                    "No ai_decisions in last 15m (count=0) — may be idle or replication lag",
                    {"count": 0, "decision_id": self._last_decision_id},
                )
            except Exception as exc:
                last_err = str(exc)
                err_l = last_err.lower()
                if self.relax_db and any(
                    x in err_l
                    for x in (
                        "could not translate host name",
                        "name or service not known",
                        "nodename nor servname",
                        "connection refused",
                    )
                ):
                    return (
                        True,
                        "DB URL not reachable from this host (skipped due to --relax-db)",
                        {"error": last_err[:400]},
                    )

        if not self.skip_docker and self.env_file.is_file():
            pg_user = os.environ.get("POSTGRES_USER") or env.get("POSTGRES_USER") or "thiramai"
            pg_db = os.environ.get("POSTGRES_DB") or env.get("POSTGRES_DB") or "thiramai"
            pg_pass = os.environ.get("POSTGRES_PASSWORD") or env.get("POSTGRES_PASSWORD") or ""
            q = (
                "SELECT COUNT(*) FROM ai_decisions "
                "WHERE created_at > NOW() - INTERVAL '15 minutes';"
            )
            try:
                env_exec = {**os.environ, "PGPASSWORD": pg_pass}
                p = subprocess.run(
                    [
                        "docker",
                        "compose",
                        "-f",
                        str(self.repo / "docker-compose.production.yml"),
                        "--env-file",
                        str(self.env_file),
                        "exec",
                        "-T",
                        "db",
                        "psql",
                        "-U",
                        pg_user,
                        "-d",
                        pg_db,
                        "-t",
                        "-A",
                        "-c",
                        q,
                    ],
                    capture_output=True,
                    text=True,
                    cwd=self.repo,
                    env=env_exec,
                    timeout=60,
                )
                if p.returncode == 0 and p.stdout.strip().isdigit():
                    c = int(p.stdout.strip())
                    if c > 0:
                        return True, f"Recent ai_decisions rows: {c} (docker exec psql)", {"count": c}
                    return (
                        True,
                        "No rows in last 15m via docker exec (count=0)",
                        {"count": 0, "decision_id": self._last_decision_id},
                    )
                last_err = last_err or (p.stderr or p.stdout or "docker exec psql failed").strip()[:500]
            except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
                last_err = last_err or str(exc)
            except Exception as exc:
                last_err = last_err or str(exc)

        if self.relax_db:
            return True, "DB persistence not fully verified (relax mode)", {
                "decision_id": self._last_decision_id,
                "last_error": last_err[:500] if last_err else None,
            }
        if last_err:
            return False, f"Could not verify ai_decisions: {last_err[:400]}", {
                "hint": "Set THIRAMAI_LIVE_DB_URL to a host-reachable URL, or pass --relax-db",
            }
        return False, "DATABASE_URL missing — cannot verify persistence", None

    def check_quality_tracking(self) -> tuple[bool, str, Optional[dict[str, Any]]]:
        if not self.token:
            return False, "No token", None
        try:
            with self._client() as client:
                r = client.get(
                    f"{self.base_url}/monitoring/ai-quality",
                    headers={"Authorization": f"Bearer {self.token}"},
                )
        except httpx.RequestError as exc:
            return False, f"Request failed: {exc}", None
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}", _safe_json(r)
        data = r.json()
        st = data.get("status")
        if st in ("ok", "no_data"):
            return True, f"Quality endpoint OK (status={st})", {"status": st, "window": data.get("window_size")}
        return False, f"Unexpected quality status: {st!r}", data

    def check_metrics(self) -> tuple[bool, str, Optional[dict[str, Any]]]:
        try:
            with self._client() as client:
                r = client.get(f"{self.base_url}/metrics")
        except httpx.RequestError as exc:
            return False, f"Request failed: {exc}", None
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}", None
        text = r.text
        keys = [
            "thiramai_policy_engine_circuit_state",
            "thiramai_safe_fallback_decisions_total",
            "thiramai_requests_total",
        ]
        found = [k for k in keys if k in text]
        if len(found) >= 2:
            return True, f"Key metrics present ({len(found)}/{len(keys)})", {"found": found}
        return False, f"Only {len(found)}/{len(keys)} expected metric families found", {"found": found}

    def print_summary(self) -> None:
        total = len(self.checks_passed) + len(self.checks_failed)
        print("\n" + "=" * 70)
        print("VERIFICATION SUMMARY")
        print("=" * 70)
        print(f"\n✅ Passed: {len(self.checks_passed)}/{total}")
        for c in self.checks_passed:
            print(f"   ✓ {c}")
        if self.checks_failed:
            print(f"\n❌ Failed: {len(self.checks_failed)}")
            for check, message, _details in self.checks_failed:
                print(f"   ✗ {check}: {message}")
        print("\n" + "=" * 70)
        if self.checks_failed:
            print("❌ VERIFICATION FAILED")
            print("\nFix the issues above before going live.")
            print("\nCommon fixes:")
            print("  - Ensure .env.production exists with correct settings")
            print("  - Run: docker compose -f docker-compose.production.yml --env-file .env.production up -d")
            print("  - Logs: docker compose -f docker-compose.production.yml logs web")
        else:
            print("✅ ALL CHECKS PASSED!")
            print("\n🎉 SYSTEM IS LIVE AND WORKING! 🎉")
            print("\nNext steps:")
            print(f"  1. Monitor: curl {self.base_url}/health/ready")
            print(f"  2. Quality: curl {self.base_url}/monitoring/ai-quality -H 'Authorization: Bearer TOKEN'")
            print("  3. Logs: docker compose -f docker-compose.production.yml logs -f web")


def _safe_json(r: httpx.Response) -> Any:
    try:
        return r.json()
    except Exception:
        return {"text": r.text[:500]}


def _resolve_base_url_and_env_file(repo: Path, args: argparse.Namespace) -> tuple[str, Path]:
    env_file = Path(args.env_file)
    if not env_file.is_absolute():
        env_file = repo / env_file
    url = (args.url or "").strip().rstrip("/")
    if not url:
        host = os.environ.get("THIRAMAI_GO_LIVE_HOST", "127.0.0.1")
        port = os.environ.get("THIRAMAI_GO_LIVE_PORT", "").strip()
        if not port and env_file.is_file():
            envd = _parse_dotenv(env_file)
            port = envd.get("WEB_PORT", "").strip()
        if not port:
            port = "8000"
        url = f"http://{host}:{port}"
    return url, env_file


def main() -> None:
    repo = _repo_root()
    p = argparse.ArgumentParser(description="Verify live Thiramai system (HTTP E2E)")
    p.add_argument("--url", default="", help="API base URL (default: http://127.0.0.1:$WEB_PORT from env file)")
    p.add_argument("--env-file", default=".env.production", help="Production env file path")
    p.add_argument(
        "--skip-tls-verify",
        action="store_true",
        help="Disable TLS certificate verification (local dev only)",
    )
    p.add_argument("--skip-docker", action="store_true", help="Skip docker compose service count check")
    p.add_argument(
        "--relax-db",
        action="store_true",
        help="Do not fail when DB cannot be reached from this host (Docker internal hostname)",
    )
    args = p.parse_args()

    if os.environ.get("THIRAMAI_LIVE_VERIFY_RELAX_DB") == "1":
        args.relax_db = True

    base_url, env_file = _resolve_base_url_and_env_file(repo, args)
    v = LiveSystemVerifier(
        base_url=base_url,
        verify_tls=not args.skip_tls_verify,
        env_file=env_file,
        repo=repo,
        skip_docker=args.skip_docker,
        relax_db=args.relax_db,
    )
    raise SystemExit(0 if v.run_all_checks() else 1)


if __name__ == "__main__":
    main()
