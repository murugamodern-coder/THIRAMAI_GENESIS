#!/usr/bin/env python3
"""Static authorization coverage and API exposure audit for FastAPI routes."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ROUTES_DIR = ROOT / "api" / "routes"
REPORTS = ROOT / "reports"
REPORTS.mkdir(parents=True, exist_ok=True)

ROUTE_DECORATOR = re.compile(r"@router\.(get|post|put|delete|patch)\(")
AUTH_HINT = re.compile(r"Depends\(\s*get_current_user|CurrentUser|require_|authorize|is_admin|is_staff")
PUBLIC_SAFE_FILES = {
    "api/routes/health.py",
    "api/routes/jarvis_bridge.py",
    "api/routes/metrics_autonomy.py",
}


def _scan_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    route_count = len(ROUTE_DECORATOR.findall(text))
    auth_markers = len(AUTH_HINT.findall(text))
    rel = str(path.relative_to(ROOT)).replace("\\", "/")
    likely_unprotected = route_count > 0 and auth_markers == 0 and rel not in PUBLIC_SAFE_FILES
    return {
        "file": rel,
        "route_count": route_count,
        "auth_markers": auth_markers,
        "likely_unprotected": likely_unprotected,
        "public_safe": rel in PUBLIC_SAFE_FILES,
    }


def main() -> int:
    files = sorted(ROUTES_DIR.glob("*.py"))
    rows = [_scan_file(p) for p in files]
    total_routes = sum(int(r["route_count"]) for r in rows)
    likely_unprotected = [r for r in rows if r["likely_unprotected"]]

    payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "api/routes/*.py",
        "total_files": len(rows),
        "total_routes": total_routes,
        "files_with_likely_unprotected_routes": len(likely_unprotected),
        "likely_unprotected_files": likely_unprotected,
        "details": rows,
        "note": "Static heuristic only; verify with route-level integration tests.",
    }
    (REPORTS / "security_authz_coverage.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "total_routes": total_routes,
                "likely_unprotected_files": len(likely_unprotected),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

