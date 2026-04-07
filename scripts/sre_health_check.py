#!/usr/bin/env python3
"""
SRE health probe — CLI wrapper. Core logic: ``services.sre_health_report``.

Usage (from repo root)::

    python scripts/sre_health_check.py
    python scripts/sre_health_check.py --profile production
    python scripts/sre_health_check.py --emit-json-only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from services.sre_health_report import (
        _executive_lines,
        _load_dotenv,
        _scaling_intelligence_console_lines,
        build_sre_health_report,
    )

    _load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="development", choices=("development", "production"))
    ap.add_argument(
        "--emit-json-only",
        action="store_true",
        help="Print only the JSON report (no executive / wound header lines).",
    )
    args = ap.parse_args()

    report = build_sre_health_report(profile=args.profile, write_reflection=True)

    if not args.emit_json_only:
        for line in _executive_lines(report):
            print(line)
        for line in _scaling_intelligence_console_lines(report.get("scaling_intelligence") or {}):
            print(line)
        print()

    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
