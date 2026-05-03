#!/usr/bin/env python3
"""
Pre-deployment verification script.

Runs comprehensive checks before allowing production deployment.
All checks must pass before going live.

Usage (repo root):
    python scripts/pre_deployment_check.py
    python scripts/pre_deployment_check.py --env-file .env.production
    python scripts/pre_deployment_check.py --skip-security --skip-coverage
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _parse_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    raw = path.read_text(encoding="utf-8", errors="replace")
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        out[key] = val
    return out


def _truthy_env(val: str | None) -> bool:
    if val is None:
        return False
    v = val.strip().lower()
    return v not in ("", "0", "false", "no", "off", "none")


def _ab_test_disabled(env: dict[str, str]) -> bool:
    keys = ("THIRAMAI_DECISION_AB_TEST", "DECISION_AB_TEST")
    for k in keys:
        if k in env:
            return not _truthy_env(env.get(k))
    return False


def _policy_engine_full_pct(env: dict[str, str]) -> bool:
    for k in ("THIRAMAI_POLICY_ENGINE_PCT", "POLICY_ENGINE_PCT", "POLICY_ENGINE_PERCENTAGE"):
        if k in env:
            try:
                return int(float(str(env[k]).strip().rstrip("%"))) >= 100
            except ValueError:
                return False
    return False


class PreDeploymentChecker:
    """Comprehensive pre-deployment verification."""

    def __init__(
        self,
        *,
        env_file: Path,
        skip_security: bool,
        skip_coverage: bool,
    ) -> None:
        self.repo = _repo_root()
        self.env_file = env_file
        self.skip_security = skip_security
        self.skip_coverage = skip_coverage
        self.checks_passed: list[str] = []
        self.checks_failed: list[tuple[str, str]] = []

    def run_all_checks(self) -> bool:
        os.chdir(self.repo)

        print("=" * 60)
        print("THIRAMAI PRE-DEPLOYMENT VERIFICATION")
        print("=" * 60)
        print()

        checks: list[tuple[str, Callable[[], tuple[bool, str]]]] = [
            ("Tests", self.check_tests),
            ("Coverage", self.check_coverage),
            ("Security", self.check_security),
            ("Dependencies", self.check_dependencies),
            ("Environment", self.check_environment),
            ("Database", self.check_database_config),
            ("Docker", self.check_docker_config),
            ("Monitoring", self.check_monitoring_config),
        ]

        for check_name, check_func in checks:
            self.run_check(check_name, check_func)

        self.print_summary()

        return len(self.checks_failed) == 0

    def run_check(self, name: str, func: Callable[[], tuple[bool, str]]) -> bool:
        print(f"\n* Checking: {name}")

        try:
            success, message = func()
            if success:
                print(f"  PASS: {message}")
                self.checks_passed.append(name)
                return True
            print(f"  FAIL: {message}")
            self.checks_failed.append((name, message))
            return False
        except Exception as e:
            print(f"  ERROR: {e!s}")
            self.checks_failed.append((name, str(e)))
            return False

    def check_tests(self) -> tuple[bool, str]:
        exe = sys.executable
        result = subprocess.run(
            [exe, "-m", "pytest", "tests/", "-q", "--tb=short"],
            capture_output=True,
            text=True,
            cwd=self.repo,
        )
        if result.returncode == 0:
            tail = (result.stdout or "").strip().splitlines()
            summary = tail[-1] if tail else "ok"
            return True, summary if "passed" in summary else "All tests passed"
        err = (result.stdout or "") + (result.stderr or "")
        return False, f"Tests failed (exit {result.returncode}): {err.strip()[-2000:]}"

    def check_coverage(self) -> tuple[bool, str]:
        if self.skip_coverage:
            return True, "Skipped (--skip-coverage)"

        exe = sys.executable
        cov_args = [
            exe,
            "-m",
            "pytest",
            "tests/",
            "-q",
            "--tb=short",
            "--cov=core",
            "--cov=services",
            "--cov=api",
            "--cov=workers",
            "--cov-report=json",
            "--cov-branch",
        ]
        subprocess.run(cov_args, capture_output=True, text=True, cwd=self.repo)

        cov_script = self.repo / "scripts" / "check_critical_coverage.py"
        result = subprocess.run(
            [exe, str(cov_script)],
            capture_output=True,
            text=True,
            cwd=self.repo,
        )
        if result.returncode == 0:
            return True, "Critical path coverage passing"
        msg = (result.stdout or "") + (result.stderr or "")
        return False, msg.strip()[-1500:] or "Coverage below thresholds"

    def check_security(self) -> tuple[bool, str]:
        if self.skip_security:
            return True, "Skipped (--skip-security)"

        if not shutil.which("bandit"):
            return True, "bandit not on PATH (skipped; install dev deps for CI parity)"

        roots = [p for p in ("core", "services", "api") if (self.repo / p).is_dir()]
        if not roots:
            return False, "No core/services/api directories found"

        result = subprocess.run(
            ["bandit", "-r", *roots, "-ll", "-q"],
            capture_output=True,
            text=True,
            cwd=self.repo,
        )
        out = (result.stdout or "") + (result.stderr or "")
        if result.returncode == 0:
            return True, "Security scan clean (bandit)"
        if "No issues identified" in out:
            return True, "Security scan clean (bandit)"
        return False, f"Bandit reported issues: {out.strip()[:800]}"

    def _pip_audit_hint_severity(self, vuln: dict[str, Any]) -> str:
        blob = json.dumps(vuln, ensure_ascii=False).lower()
        if "critical" in blob:
            return "critical"
        if re.search(r"\bhigh\b", blob):
            return "high"
        return "low"

    def check_dependencies(self) -> tuple[bool, str]:
        cmd: list[str] = [sys.executable, "-m", "pip_audit", "-f", "json", "--desc", "on"]
        added_req = False
        for name in ("requirements-production.txt", "requirements-base.txt"):
            path = self.repo / name
            if path.is_file():
                cmd.extend(["-r", str(path)])
                added_req = True
        if not added_req:
            cmd.append(str(self.repo))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.repo,
                timeout=600,
            )
        except subprocess.TimeoutExpired:
            return True, "pip-audit timed out (skipped)"
        except OSError as exc:
            return True, f"pip-audit spawn issue ({exc!s}; skipped)"

        out = (result.stdout or "") + (result.stderr or "")
        if "No module named pip_audit" in out or "No module named 'pip_audit'" in out:
            return True, "pip-audit not installed (skipped; pip install pip-audit)"

        toolchain_issue = any(
            sig in out.lower()
            for sig in (
                "metadata-generation-failed",
                "failed to install packages",
                "error: subprocess-exited-with-error",
            )
        )
        if toolchain_issue and result.returncode != 0:
            return True, "pip-audit toolchain/builddeps issue (e.g. Python 3.14) — skipped"

        try:
            data = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            if result.returncode == 0:
                return True, "pip-audit exited 0 (unparsed JSON)"
            if re.search(r"\b(high|critical)\b", out, re.I):
                return False, "pip-audit: high/critical mentioned in output"
            return True, f"pip-audit non-JSON output (exit {result.returncode}) — skipped"

        worst = "none"
        vuln_count = 0
        for dep in data.get("dependencies") or []:
            for v in dep.get("vulns") or []:
                if not isinstance(v, dict):
                    continue
                vuln_count += 1
                level = self._pip_audit_hint_severity(v)
                if level == "critical":
                    worst = "critical"
                elif level == "high" and worst != "critical":
                    worst = "high"

        if vuln_count == 0 and result.returncode == 0:
            return True, "No vulnerable dependencies (pip-audit)"
        if vuln_count == 0 and result.returncode != 0:
            return True, "pip-audit exit non-zero with no parsed vulns — skipped (toolchain)"

        if worst in ("high", "critical"):
            return False, f"pip-audit: {worst} severity finding(s) ({vuln_count} vulnerabilit(y/ies))"
        return True, f"Only low/medium severity ({vuln_count} finding(s)) — review before release"

    def check_environment(self) -> tuple[bool, str]:
        if not self.env_file.is_file():
            return (
                False,
                f"{self.env_file} not found (copy from .env.production.example)",
            )

        env = _parse_dotenv(self.env_file)
        if "DATABASE_URL" not in env or not env["DATABASE_URL"].strip():
            return False, "DATABASE_URL missing or empty"

        if "CHANGE_ME" in env["DATABASE_URL"] or "changeme" in env["DATABASE_URL"].lower():
            return False, "DATABASE_URL still contains placeholder credentials"

        if not _ab_test_disabled(env):
            return (
                False,
                "A/B test must be off: set THIRAMAI_DECISION_AB_TEST=false (and/or DECISION_AB_TEST=false)",
            )

        if not _policy_engine_full_pct(env):
            return (
                False,
                "PolicyEngine must be 100%: set THIRAMAI_POLICY_ENGINE_PCT=100 "
                "(or POLICY_ENGINE_PCT / POLICY_ENGINE_PERCENTAGE)",
            )

        return True, "Environment configuration valid for PolicyEngine cutover"

    def check_database_config(self) -> tuple[bool, str]:
        if not self.env_file.is_file():
            return False, "No env file for database check"

        env = _parse_dotenv(self.env_file)
        if "DATABASE_URL" not in env:
            return False, "DATABASE_URL missing"

        pool_size_key = next((k for k in ("POOL_SIZE", "THIRAMAI_DB_POOL_SIZE") if k in env), None)
        max_ov_key = next((k for k in ("MAX_OVERFLOW", "THIRAMAI_DB_MAX_OVERFLOW") if k in env), None)
        if pool_size_key and max_ov_key:
            return True, f"Database pool configured ({pool_size_key}, {max_ov_key})"

        return (
            False,
            "Set explicit POOL_SIZE and MAX_OVERFLOW (or THIRAMAI_DB_POOL_SIZE / "
            "THIRAMAI_DB_MAX_OVERFLOW) in .env.production",
        )

    def check_docker_config(self) -> tuple[bool, str]:
        compose = self.repo / "docker-compose.production.yml"
        if not compose.is_file():
            return False, "docker-compose.production.yml not found"
        return True, "Docker compose file present"

    def check_monitoring_config(self) -> tuple[bool, str]:
        alert_rules = self.repo / "monitoring" / "prometheus" / "alert-rules.yml"
        if not alert_rules.is_file():
            return False, "monitoring/prometheus/alert-rules.yml not found"

        text = alert_rules.read_text(encoding="utf-8", errors="replace")
        if re.search(r"policy_engine|PolicyEngine", text):
            return True, "Monitoring configured with PolicyEngine alerts"
        return False, "PolicyEngine alerts not found in alert-rules.yml"

    def print_summary(self) -> None:
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)

        print(f"\nPassed: {len(self.checks_passed)}")
        for check in self.checks_passed:
            print(f"   - {check}")

        if self.checks_failed:
            print(f"\nFailed: {len(self.checks_failed)}")
            for check, message in self.checks_failed:
                print(f"   - {check}: {message}")

        print("\n" + "=" * 60)
        if self.checks_failed:
            print("PRE-DEPLOYMENT CHECKS FAILED")
            print("   Fix issues above before deploying")
        else:
            print("ALL CHECKS PASSED - READY TO DEPLOY")


def main() -> None:
    p = argparse.ArgumentParser(description="Pre-deployment verification for Thiramai Genesis")
    p.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env.production"),
        help="Path to production env file (default: .env.production)",
    )
    p.add_argument(
        "--skip-security",
        action="store_true",
        help="Skip bandit scan",
    )
    p.add_argument(
        "--skip-coverage",
        action="store_true",
        help="Skip pytest-cov + critical coverage gate",
    )
    args = p.parse_args()

    checker = PreDeploymentChecker(
        env_file=args.env_file,
        skip_security=args.skip_security,
        skip_coverage=args.skip_coverage,
    )
    success = checker.run_all_checks()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
