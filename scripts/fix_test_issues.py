#!/usr/bin/env python3
"""
Diagnose common test setup issues and run pytest with short tracebacks.

Usage (repo root):
    python scripts/fix_test_issues.py
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _repo() -> Path:
    return Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose tests and run pytest")
    parser.add_argument(
        "pytest_args",
        nargs="*",
        default=["tests/", "-q", "--tb=short"],
        help="Extra pytest args (default: tests/ -q --tb=short)",
    )
    args = parser.parse_args()

    repo = _repo()

    print("Diagnosing test environment...")
    print()

    print("* Core test dependencies")
    missing: list[str] = []
    for mod in ("pytest", "httpx"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        print(f"  Installing missing: {missing}")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pytest", "pytest-asyncio", "pytest-cov", "httpx"],
            check=False,
        )
    else:
        print("  OK: pytest + httpx importable")

    print("\n* Compile tests (syntax)")
    compile_run = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", str(repo / "tests")],
        cwd=str(repo),
    )
    if compile_run.returncode != 0:
        print("  FAIL: compileall reported errors (see above)")
    else:
        print("  OK: tests compile")

    print("\n* Optional: core.database import (may need DATABASE_URL)")
    try:
        sys.path.insert(0, str(repo))
        import core.database  # noqa: F401 — side effect: import check
        print("  OK: core.database imports")
    except Exception as exc:  # noqa: BLE001
        print(f"  WARN: {type(exc).__name__}: {exc}")

    print("\n" + "=" * 70)
    print("Running pytest:", " ".join(args.pytest_args))
    print("=" * 70)

    rc = subprocess.run([sys.executable, "-m", "pytest", *args.pytest_args], cwd=str(repo)).returncode
    print("=" * 70)
    if rc != 0:
        print(f"\nTests failed (exit {rc}).")
        print("\nHints:")
        print("  - Use Python 3.12 if 3.14 breaks a dependency.")
        print("  - Start Postgres if tests need DB: docker compose -f docker-compose.production.yml --env-file .env.production up -d db")
        print("  - Re-run with: python scripts/fix_test_issues.py tests/path/test_foo.py -vv --tb=long")
        raise SystemExit(rc)
    print("\nAll tests passed.")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
