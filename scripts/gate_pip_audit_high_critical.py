#!/usr/bin/env python3
"""
Run pip-audit on each given requirements file and exit non-zero if any finding
has CVSS v3 base score >= 7.0 (NVD: High) or >= 9.0 (Critical), using OSV records.

pip-audit 2.x does not expose severity thresholds on the CLI; this script adds that gate.
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

try:
    from cvss import CVSS3
except ImportError as e:  # pragma: no cover
    print("Install the `cvss` package: pip install cvss", file=sys.stderr)
    raise SystemExit(2) from e

OSV_VULN_URL = "https://api.osv.dev/v1/vulns/{id}"
HIGH_MIN = 7.0
CRITICAL_MIN = 9.0


def _base_score_from_osv_severity(severity: list[dict[str, Any]]) -> float | None:
    best: float | None = None
    for item in severity:
        score = item.get("score")
        if not score or not isinstance(score, str):
            continue
        if score.startswith("CVSS:3"):
            try:
                val = float(CVSS3(score).scores()[0])
            except Exception:
                continue
        else:
            try:
                val = float(score)
            except ValueError:
                continue
        best = val if best is None else max(best, val)
    return best


def _fetch_osv(vuln_id: str) -> dict[str, Any] | None:
    url = OSV_VULN_URL.format(id=urllib.parse.quote(vuln_id, safe=""))
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    except Exception:
        return None


def _audit_requirements_files(paths: list[str]) -> dict[str, Any]:
    cmd = [sys.executable, "-m", "pip_audit", "-f", "json"]
    for path in paths:
        cmd.extend(["-r", path])
    p = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
    )
    if p.returncode not in (0, 1) or not p.stdout.strip():
        print(p.stderr or p.stdout, file=sys.stderr)
        raise SystemExit(p.returncode or 2)
    return json.loads(p.stdout)


def main() -> None:
    req_files = sys.argv[1:]
    if not req_files:
        print("usage: gate_pip_audit_high_critical.py <requirements.txt> ...", file=sys.stderr)
        raise SystemExit(2)

    data = _audit_requirements_files(req_files)
    vuln_ids: set[str] = set()
    for dep in data.get("dependencies", []):
        for v in dep.get("vulns") or []:
            vid = v.get("id")
            if isinstance(vid, str):
                vuln_ids.add(vid)

    if not vuln_ids:
        print("pip-audit: no vulnerabilities reported (severity gate not needed).")
        return

    failed: list[tuple[str, float, str]] = []
    cache: dict[str, dict[str, Any] | None] = {}
    for vid in sorted(vuln_ids):
        if vid not in cache:
            cache[vid] = _fetch_osv(vid)
        record = cache[vid]
        if not record:
            print(f"[warn] OSV: no record for {vid} — skipping severity gate for this id.")
            continue
        score = _base_score_from_osv_severity(record.get("severity") or [])
        if score is None:
            print(f"[warn] OSV: no CVSS for {vid} — skipping severity gate for this id.")
            continue
        label = "CRITICAL" if score >= CRITICAL_MIN else "HIGH" if score >= HIGH_MIN else "lower"
        if score >= HIGH_MIN:
            failed.append((vid, score, label))

    if failed:
        print("Blocked: High or Critical vulnerabilities:", file=sys.stderr)
        for vid, score, label in failed:
            print(f"  {vid}  CVSS≈{score:.1f}  ({label})", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
