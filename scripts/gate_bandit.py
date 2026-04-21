#!/usr/bin/env python3
"""Gate Bandit JSON output: fail on HIGH, warn on MEDIUM, print summary."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _load(path: str) -> dict:
    p = Path(path)
    if not p.is_file():
        print(f"error: bandit report not found: {path}", file=sys.stderr)
        raise SystemExit(2)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"error: invalid bandit json: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: gate_bandit.py <bandit.json>", file=sys.stderr)
        raise SystemExit(2)

    data = _load(sys.argv[1])
    results = data.get("results", [])

    high = []
    medium = []
    low = 0

    for item in results:
        sev = str(item.get("issue_severity", "")).upper()
        issue = str(item.get("issue_text", ""))
        filename = str(item.get("filename", ""))
        line = item.get("line_number", "?")
        detail = f"{filename}:{line} - {issue}"
        if sev == "HIGH":
            high.append(detail)
        elif sev == "MEDIUM":
            medium.append(detail)
        else:
            low += 1

    print("Bandit security summary")
    print(f"  HIGH:   {len(high)}")
    print(f"  MEDIUM: {len(medium)}")
    print(f"  LOW:    {low}")

    if medium:
        print("\n[warn] Medium severity findings:")
        for item in medium:
            print(f"  - {item}")

    if high:
        print("\n[fail] High severity findings:")
        for item in high:
            print(f"  - {item}")
        raise SystemExit(1)

    print("\nBandit gate passed.")


if __name__ == "__main__":
    main()
