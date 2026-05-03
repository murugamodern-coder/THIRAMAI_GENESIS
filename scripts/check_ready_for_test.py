#!/usr/bin/env python3
"""
Pre-test validation — ensure required files and scripts exist before running the local live test.

Usage (from repo root):
    python scripts/check_ready_for_test.py
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from typing import Callable


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


class PreTestValidator:
    def __init__(self) -> None:
        self.repo = _repo_root()
        self.checks_passed: list[str] = []
        self.checks_failed: list[tuple[str, str]] = []

    def run_all_checks(self) -> bool:
        os.chdir(self.repo)
        print("=" * 70)
        print("PRE-TEST VALIDATION - CHECKING SYSTEM READINESS")
        print("=" * 70)
        print()

        checks: list[tuple[str, Callable[[], tuple[bool, str]]]] = [
            ("Required Files", self.check_required_files),
            ("Test Scripts", self.check_test_scripts),
            ("Deployment Scripts", self.check_deployment_scripts),
            ("Environment Template", self.check_env_template),
            ("Docker Compose", self.check_docker_compose),
            ("Scripts Executable", self.check_executable_bits),
        ]

        for check_name, check_func in checks:
            self.run_check(check_name, check_func)

        self.print_summary()
        return len(self.checks_failed) == 0

    def run_check(self, name: str, func: Callable[[], tuple[bool, str]]) -> bool:
        print(f"* {name}...", end=" ", flush=True)
        try:
            passed, message = func()
            if passed:
                print(f"OK: {message}")
                self.checks_passed.append(name)
                return True
            print(f"FAIL: {message}")
            self.checks_failed.append((name, message))
            return False
        except Exception as e:
            print(f"ERROR: {e}")
            self.checks_failed.append((name, str(e)))
            return False

    def check_required_files(self) -> tuple[bool, str]:
        required = [
            "README.md",
            "requirements-base.txt",
            "docker-compose.production.yml",
            ".env.production.example",
        ]
        missing = [f for f in required if not (self.repo / f).exists()]
        if missing:
            return False, f"Missing: {', '.join(missing)}"
        return True, "All required files present"

    def check_test_scripts(self) -> tuple[bool, str]:
        scripts = [
            "scripts/run_local_live_test.sh",
            "scripts/analyze_test_results.py",
            "scripts/verify_live_system.py",
        ]
        missing = [s for s in scripts if not (self.repo / s).exists()]
        if missing:
            return False, f"Missing: {', '.join(missing)}"
        return True, "All test scripts present"

    def check_deployment_scripts(self) -> tuple[bool, str]:
        scripts = [
            "scripts/pre_deployment_check.py",
            "scripts/go_live.sh",
            "scripts/full_go_live.sh",
            "scripts/verify_deployment.py",
            "scripts/setup_production_env.sh",
            "scripts/fix_test_issues.py",
            "scripts/check_ready_for_test.py",
        ]
        missing = [s for s in scripts if not (self.repo / s).exists()]
        if missing:
            return False, f"Missing: {', '.join(missing)}"
        return True, "All deployment scripts present"

    def check_env_template(self) -> tuple[bool, str]:
        template = self.repo / ".env.production.example"
        if not template.exists():
            return False, "Template not found"
        content = template.read_text(encoding="utf-8", errors="replace")
        required_settings = [
            "DATABASE_URL",
            "THIRAMAI_DECISION_AB_TEST",
            "JWT_SECRET_KEY",
        ]
        pool_ok = ("POOL_SIZE" in content or "THIRAMAI_DB_POOL_SIZE" in content) and (
            "MAX_OVERFLOW" in content or "THIRAMAI_DB_MAX_OVERFLOW" in content
        )
        missing = [s for s in required_settings if s not in content]
        if not pool_ok:
            missing.append("POOL_SIZE+MAX_OVERFLOW (or THIRAMAI_DB_* pool keys)")
        if missing:
            return False, f"Template missing: {', '.join(missing)}"
        return True, "Environment template valid"

    def check_docker_compose(self) -> tuple[bool, str]:
        compose = self.repo / "docker-compose.production.yml"
        if not compose.exists():
            return False, "File not found"
        content = compose.read_text(encoding="utf-8", errors="replace")
        if "web:" not in content or "db:" not in content:
            return False, "Missing web or db service"
        return True, "Docker compose file valid"

    def check_executable_bits(self) -> tuple[bool, str]:
        scripts = [
            "scripts/run_local_live_test.sh",
            "scripts/go_live.sh",
            "scripts/full_go_live.sh",
            "scripts/setup_production_env.sh",
        ]
        if os.name == "nt" or sys.platform == "win32":
            return True, "Skipped (Windows: use Git Bash or bash scripts/run_local_live_test.sh)"
        non_executable: list[str] = []
        for script in scripts:
            path = self.repo / script
            if not path.exists():
                continue
            mode = path.stat().st_mode
            if not (mode & stat.S_IXUSR or mode & stat.S_IXGRP or mode & stat.S_IXOTH):
                non_executable.append(script)
        if non_executable:
            hint = "; run: git update-index --chmod=+x " + " ".join(non_executable)
            return False, f"Not executable: {', '.join(non_executable)} {hint}"
        return True, "Shell scripts are executable"

    def print_summary(self) -> None:
        print("\n" + "=" * 70)
        print("VALIDATION SUMMARY")
        print("=" * 70)
        print(f"\nPassed: {len(self.checks_passed)}")
        if self.checks_failed:
            print(f"Failed: {len(self.checks_failed)}")
            print("\nIssues found:")
            for check, message in self.checks_failed:
                print(f"  FAIL {check}: {message}")
            print("\n" + "=" * 70)
            print("SYSTEM NOT READY FOR TESTING")
            print("\nFix the issues above before running the live test.")
            return
        print("\n" + "=" * 70)
        print("SYSTEM READY FOR LIVE TESTING")
        print("\nNext steps:")
        print("\n1. Ensure .env.production exists:")
        print("   bash scripts/setup_production_env.sh")
        print("   # Or: cp .env.production.example .env.production && edit secrets")
        print("\n2. Run live test (Git Bash / macOS / Linux):")
        print("   ./scripts/run_local_live_test.sh")
        print("\n3. Analyze results:")
        print("   python scripts/analyze_test_results.py")


def main() -> None:
    validator = PreTestValidator()
    success = validator.run_all_checks()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
