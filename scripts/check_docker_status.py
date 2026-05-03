#!/usr/bin/env python3
"""
Check Docker Compose service status and readiness for docker-compose.production.yml.

Run from any directory; resolves project root from this script's location.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any


class DockerStatusChecker:
    """Check Docker compose services status."""

    def __init__(self, project_root: Path | None = None) -> None:
        root = project_root or Path(__file__).resolve().parent.parent
        self.project_root = root
        self.compose_file = root / "docker-compose.production.yml"
        self.env_file = root / ".env.production"
        self.compose_cmd = [
            "docker",
            "compose",
            "-f",
            str(self.compose_file),
            "--env-file",
            str(self.env_file),
            "ps",
            "--format",
            "json",
        ]

    def check_all(self, wait: bool = False, timeout: int = 300) -> bool:
        print("=" * 70)
        print("DOCKER SERVICES STATUS CHECK")
        print("=" * 70)
        print()

        if not self.compose_file.is_file():
            print("ERROR: docker-compose.production.yml not found")
            return False
        if not self.env_file.is_file():
            print("ERROR: .env.production not found")
            return False

        if wait:
            return self.wait_for_healthy(timeout)
        return self.check_current_status()

    def check_current_status(self) -> bool:
        services = self.get_services_status()
        if not services:
            print("No services found (Docker not running, wrong project, or compose failed).")
            return False

        print("Service Status:")
        print("-" * 70)

        all_healthy = True
        for service in services:
            name = str(service.get("Service", "unknown"))
            state = str(service.get("State", "unknown"))
            status = str(service.get("Status", ""))
            health = str(service.get("Health") or "").strip()
            if not health and status:
                if "(healthy)" in status.lower():
                    health = "healthy"
                elif "(unhealthy)" in status.lower():
                    health = "unhealthy"
                elif "(health: starting)" in status.lower() or "(starting)" in status.lower():
                    health = "starting"

            if state == "running" and (not health or health == "healthy"):
                icon = "✅"
            elif state == "running":
                icon = "⚠️ "
                all_healthy = False
            else:
                icon = "❌"
                all_healthy = False

            print(f"{icon} {name:15} | {state:10} | {status[:45]:45}")

            if health and health != "healthy":
                print(f"       Health: {health}")

        print("-" * 70)

        if all_healthy:
            print("\n✅ All services healthy!")
            return True
        print("\n⚠️  Some services not healthy yet")
        return False

    def wait_for_healthy(self, timeout: int = 300) -> bool:
        print(f"Waiting for services to become healthy (timeout: {timeout}s)...")
        print()

        start = time.time()
        while time.time() - start < timeout:
            services = self.get_services_status()
            if not services:
                print(".", end="", flush=True)
                time.sleep(5)
                continue

            all_ok = True
            for service in services:
                state = str(service.get("State", ""))
                status = str(service.get("Status", ""))
                health = str(service.get("Health") or "").strip()
                if not health and status:
                    if "(healthy)" in status.lower():
                        health = "healthy"
                    elif "(unhealthy)" in status.lower():
                        health = "unhealthy"
                    elif "starting" in status.lower():
                        health = "starting"

                if state != "running":
                    all_ok = False
                    break
                if health and health != "healthy":
                    all_ok = False
                    break

            if all_ok:
                print("\n\n✅ All services are healthy!")
                self.check_current_status()
                return True

            elapsed = int(time.time() - start)
            print(f"\r⏳ Waiting... {elapsed}s / {timeout}s", end="", flush=True)
            time.sleep(5)

        print(f"\n\n❌ Timeout after {timeout}s")
        print("\nCurrent status:")
        self.check_current_status()
        return False

    def get_services_status(self) -> list[dict[str, Any]]:
        try:
            result = subprocess.run(
                self.compose_cmd,
                capture_output=True,
                text=True,
                check=False,
                cwd=str(self.project_root),
                timeout=120,
                env={**os.environ},
            )
        except FileNotFoundError:
            return []
        except subprocess.TimeoutExpired:
            return []

        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            if err:
                print(err)
            return []

        raw = result.stdout.strip()
        if not raw:
            return []

        services: list[dict[str, Any]] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                services.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return services


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Docker Compose services status")
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Wait for services to become healthy",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Wait timeout in seconds (default: 300)",
    )
    args = parser.parse_args()

    checker = DockerStatusChecker()
    ok = checker.check_all(wait=args.wait, timeout=args.timeout)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
