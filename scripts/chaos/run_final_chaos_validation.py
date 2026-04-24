#!/usr/bin/env python3
"""Final chaos/reliability evidence runner for local or staging environments."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
REPORTS.mkdir(parents=True, exist_ok=True)


def _run(cmd: list[str], timeout: int = 300) -> dict:
    p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout)
    out = ((p.stdout or "") + ("\n" + p.stderr if p.stderr else "")).strip()
    return {"cmd": " ".join(cmd), "exit_code": int(p.returncode), "output": out[:120000]}


def main() -> int:
    ts = datetime.now(timezone.utc).isoformat()
    checks = []

    checks.append(
        {
            "name": "worker_resilience",
            **_run([sys.executable, "-m", "pytest", "tests/test_worker_resilience.py", "-q"], timeout=180),
        }
    )
    checks.append(
        {
            "name": "autonomous_loop_safety",
            **_run([sys.executable, "-m", "pytest", "tests/test_hardened_loop.py", "tests/test_autonomous_loop.py", "-q"], timeout=240),
        }
    )
    checks.append(
        {
            "name": "stress_concurrent_sells",
            **_run([sys.executable, "-m", "pytest", "tests/test_stress_concurrent_sells.py", "-q"], timeout=240),
        }
    )

    all_pass = all(int(c["exit_code"]) == 0 for c in checks)
    payload = {
        "timestamp_utc": ts,
        "status": "pass" if all_pass else "partial",
        "checks": checks,
        "notes": [
            "This script validates local reliability invariants.",
            "Live DB/Redis/pod-kill chaos must be executed in staging/production infrastructure.",
        ],
    }
    (REPORTS / "chaos_validation_report.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"status": payload["status"], "checks": len(checks)}, ensure_ascii=False))
    return 0 if all_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())

