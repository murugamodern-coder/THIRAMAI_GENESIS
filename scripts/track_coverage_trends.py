#!/usr/bin/env python3
"""
Append aggregate coverage from coverage.json into coverage-trends.json (last N entries).

Run after pytest with --cov-report=json. Optional: commit coverage-trends.json or attach as CI artifact.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def get_git_commit() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_repo_root(),
            capture_output=True,
            text=True,
            check=False,
        )
        if r.returncode == 0:
            return (r.stdout or "").strip()[:40]
    except OSError:
        pass
    return "unknown"


def load_coverage_summary() -> dict[str, object]:
    path = _repo_root() / "coverage.json"
    if not path.is_file():
        print("ERROR: coverage.json not found. Run pytest with --cov-report=json", file=sys.stderr)
        sys.exit(1)
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    totals = data.get("totals") or {}
    covered = totals.get("covered_lines")
    num = totals.get("num_statements")
    pct = totals.get("percent_covered")
    if pct is None and covered is not None and num:
        try:
            pct = 100.0 * float(covered) / float(num)
        except ZeroDivisionError:
            pct = 0.0
    return {
        "percent_covered": round(float(pct or 0.0), 2),
        "covered_lines": covered,
        "num_statements": num,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "commit": get_git_commit(),
    }


def save_trend(entry: dict[str, object], *, keep_last: int = 100) -> None:
    trends_file = _repo_root() / "coverage-trends.json"
    if trends_file.is_file():
        with trends_file.open(encoding="utf-8") as f:
            trends = json.load(f)
    else:
        trends = {"history": []}
    hist = list(trends.get("history") or [])
    hist.append(entry)
    trends["history"] = hist[-keep_last:]
    with trends_file.open("w", encoding="utf-8") as f:
        json.dump(trends, f, indent=2)


def main() -> None:
    coverage = load_coverage_summary()
    save_trend(coverage)
    print(f"Recorded coverage: {coverage['percent_covered']}% (commit={coverage['commit']})")


if __name__ == "__main__":
    main()
