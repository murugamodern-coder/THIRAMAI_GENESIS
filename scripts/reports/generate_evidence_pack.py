#!/usr/bin/env python3
"""Generate consolidated reliability/security evidence pack markdown."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
REPORTS.mkdir(parents=True, exist_ok=True)


def _read_json(name: str) -> dict:
    p = REPORTS / name
    if not p.exists():
        return {"status": "missing", "file": name}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "invalid", "file": name, "error": str(exc)}


def main() -> int:
    chaos = _read_json("chaos_validation_report.json")
    dep = _read_json("security_dependency_scan.json")
    authz = _read_json("security_authz_coverage.json")

    lines = [
        "# THIRAMAI Evidence Pack",
        "",
        f"Generated (UTC): {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Chaos Validation",
        f"- Status: `{chaos.get('status', 'missing')}`",
    ]
    for c in list(chaos.get("checks") or []):
        lines.append(f"- {c.get('name')}: exit_code={c.get('exit_code')}")

    lines.extend(
        [
            "",
            "## Security Dependency Scan",
            f"- Status: `{dep.get('status', 'missing')}`",
            f"- Summary: {dep.get('summary', dep.get('file', 'n/a'))}",
            "",
            "## AuthZ Coverage Audit",
            f"- Total routes scanned: `{authz.get('total_routes', 'n/a')}`",
            f"- Likely unprotected route files: `{authz.get('files_with_likely_unprotected_routes', 'n/a')}`",
            "",
            "## Notes",
            "- Static audits and local chaos checks are included.",
            "- Live infrastructure chaos (DB/Redis/pod kill) should be run in staging/prod.",
        ]
    )
    out = "\n".join(lines) + "\n"
    (REPORTS / "ENTERPRISE_EVIDENCE_PACK.md").write_text(out, encoding="utf-8")
    print("reports/ENTERPRISE_EVIDENCE_PACK.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

