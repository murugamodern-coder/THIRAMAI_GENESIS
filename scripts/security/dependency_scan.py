#!/usr/bin/env python3
"""Run dependency vulnerability scan and write evidence report."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
REPORTS.mkdir(parents=True, exist_ok=True)


def _run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    out = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return int(p.returncode), out.strip()


def main() -> int:
    timestamp = datetime.now(timezone.utc).isoformat()
    status = "not_executed"
    summary = "pip-audit unavailable"
    details = ""

    code, out = _run([sys.executable, "-m", "pip_audit", "-f", "json"])
    if code == 0:
        status = "pass"
        summary = "No known vulnerabilities reported by pip-audit."
        details = out
    elif "No module named pip_audit" in out:
        status = "not_executed"
        summary = "pip-audit not installed; install with `python -m pip install pip-audit`."
        details = out
    else:
        status = "fail"
        summary = "Dependency vulnerabilities found or scan failed."
        details = out

    payload = {
        "timestamp_utc": timestamp,
        "tool": "pip-audit",
        "status": status,
        "summary": summary,
        "raw_output": details[:200000],
    }
    (REPORTS / "security_dependency_scan.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"status": status, "summary": summary}, ensure_ascii=False))
    return 0 if status in {"pass", "not_executed"} else 2


if __name__ == "__main__":
    raise SystemExit(main())

