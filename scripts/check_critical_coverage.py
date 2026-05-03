#!/usr/bin/env python3
"""
Check coverage for critical production paths (money, security, data integrity).

Usage (from repo root):
    pytest tests/ --cov=core --cov=services --cov=api --cov=workers \\
        --cov-report=json --cov-report=xml --cov-branch
    python scripts/check_critical_coverage.py

Requires coverage.json (pytest-cov / coverage.py).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# Paths use forward slashes; matcher normalizes OS-specific keys in coverage.json.
# Baselines tuned to current suite (May 2026); raise toward 85-90% on money/security paths over time.
# See docs/development/testing-coverage.md
CRITICAL_PATHS: dict[str, dict[str, Any]] = {
    "services/quant/": {
        "min_coverage": 71,
        "reason": "Trading / quant logic - financial and model risk",
    },
    "services/execution_decision_engine.py": {
        "min_coverage": 7,
        "reason": "Execution decisions - operational risk (raise toward 90% as tests land)",
    },
    "services/quant/portfolio_risk_engine.py": {
        "min_coverage": 90,
        "reason": "Portfolio risk - loss prevention",
    },
    "services/quant/walk_forward.py": {
        "min_coverage": 85,
        "reason": "Walk-forward validation - strategy confidence",
    },
    "services/quant/broker_stops.py": {
        "min_coverage": 85,
        "reason": "Stop automation - loss prevention",
    },
    "api/routes/stock_assistant.py": {
        "min_coverage": 44,
        "reason": "Broker-facing trading routes - financial risk",
    },
    "api/routes/execute.py": {
        "min_coverage": 71,
        "reason": "Money / execution routes - financial risk",
    },
    "core/security_middleware.py": {
        "min_coverage": 44,
        "reason": "Security middleware - abuse and hardening",
    },
    "api/routes/auth.py": {
        "min_coverage": 39,
        "reason": "Authentication - access control",
    },
    "core/auth.py": {
        "min_coverage": 67,
        "reason": "JWT and password crypto - access control",
    },
    "core/secrets_manager.py": {
        "min_coverage": 51,
        "reason": "Secrets handling - data breach risk",
    },
    "core/database.py": {
        "min_coverage": 43,
        "reason": "Database session factory - availability",
    },
    "services/decision_brain_v2.py": {
        "min_coverage": 70,
        "reason": "Decision brain v2 - operational correctness",
    },
    "services/decision_router.py": {
        "min_coverage": 75,
        "reason": "Decision routing - operational correctness",
    },
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _normalize_key(file_key: str, root: Path) -> str:
    """Turn coverage.json file keys into repo-relative POSIX paths."""
    raw = str(file_key).replace("\\", "/").strip()
    root_s = str(root.resolve()).replace("\\", "/").rstrip("/")
    if raw.lower().startswith(root_s.lower() + "/"):
        return raw[len(root_s) + 1 :]
    # Strip common CI prefix (/home/runner/work/repo/repo/)
    if "/THIRAMAI_GENESIS/" in raw.upper():
        idx = raw.upper().find("/THIRAMAI_GENESIS/")
        return raw[idx + len("/THIRAMAI_GENESIS/") :].lstrip("/")
    p = Path(file_key)
    if p.is_absolute():
        try:
            return p.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return p.as_posix()
    return raw.lstrip("./")


def _files_index(coverage_data: dict[str, Any], root: Path) -> dict[str, dict[str, Any]]:
    """Map normalized relative path -> file entry."""
    out: dict[str, dict[str, Any]] = {}
    for k, v in (coverage_data.get("files") or {}).items():
        norm = _normalize_key(k, root)
        out[norm] = v
    return out


def load_coverage_data(root: Path) -> dict[str, Any]:
    cov_path = root / "coverage.json"
    if not cov_path.is_file():
        alt = Path(os.environ.get("COVERAGE_FILE", ".coverage"))
        print("ERROR: coverage.json not found.", file=sys.stderr)
        print(f"  Expected: {cov_path}", file=sys.stderr)
        print("  Run: pytest tests/ --cov=core --cov=services --cov=api --cov=workers \\")
        print("         --cov-report=json --cov-report=xml --cov-branch", file=sys.stderr)
        if alt.is_file():
            print("  Hint: .coverage exists; re-run pytest with --cov-report=json", file=sys.stderr)
        sys.exit(1)
    with cov_path.open(encoding="utf-8") as f:
        return json.load(f)


def get_file_coverage(files_idx: dict[str, dict[str, Any]], rel_path: str) -> float | None:
    rel = rel_path.replace("\\", "/")
    if rel in files_idx:
        summary = files_idx[rel].get("summary") or {}
        return float(summary.get("percent_covered", 0.0))
    # Fallback: suffix match (single file name)
    matches = [k for k in files_idx if k.endswith("/" + rel) or k == rel]
    if len(matches) == 1:
        summary = files_idx[matches[0]].get("summary") or {}
        return float(summary.get("percent_covered", 0.0))
    return None


def get_directory_coverage(
    files_idx: dict[str, dict[str, Any]], dir_path: str
) -> tuple[float | None, int]:
    prefix = dir_path.replace("\\", "/")
    if not prefix.endswith("/"):
        prefix += "/"
    matching = [k for k in files_idx if "/" in k and k.startswith(prefix) and k.endswith(".py")]
    if not matching:
        matching = [k for k in files_idx if k.startswith(prefix)]
    if not matching:
        return None, 0
    total = 0.0
    for path in matching:
        summary = files_idx[path].get("summary") or {}
        total += float(summary.get("percent_covered", 0.0))
    return total / len(matching), len(matching)


def check_critical_coverage(coverage_data: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    files_idx = _files_index(coverage_data, root)
    results: list[dict[str, Any]] = []

    for path, requirements in CRITICAL_PATHS.items():
        min_cov = int(requirements["min_coverage"])
        reason = str(requirements["reason"])

        if path.endswith("/"):
            cov, nfiles = get_directory_coverage(files_idx, path)
            if cov is None or nfiles == 0:
                results.append(
                    {
                        "path": path,
                        "status": "missing",
                        "coverage": 0.0,
                        "required": min_cov,
                        "reason": reason,
                        "message": f"No files found matching {path}",
                    }
                )
                continue
            passed = cov >= min_cov
            results.append(
                {
                    "path": path,
                    "status": "pass" if passed else "fail",
                    "coverage": cov,
                    "required": min_cov,
                    "reason": reason,
                    "files": nfiles,
                    "message": f"{nfiles} files, avg {cov:.1f}%",
                }
            )
        else:
            cov = get_file_coverage(files_idx, path)
            if cov is None:
                results.append(
                    {
                        "path": path,
                        "status": "missing",
                        "coverage": 0.0,
                        "required": min_cov,
                        "reason": reason,
                        "message": "File not found in coverage report",
                    }
                )
                continue
            passed = cov >= min_cov
            results.append(
                {
                    "path": path,
                    "status": "pass" if passed else "fail",
                    "coverage": cov,
                    "required": min_cov,
                    "reason": reason,
                    "message": f"{cov:.1f}% coverage",
                }
            )
    return results


def print_results(results: list[dict[str, Any]]) -> bool:
    print("\n" + "=" * 80)
    print("CRITICAL PATH COVERAGE CHECK")
    print("=" * 80)

    passed, failed, missing = [], [], []
    for r in results:
        if r["status"] == "pass":
            passed.append(r)
        elif r["status"] == "fail":
            failed.append(r)
        else:
            missing.append(r)

    if failed:
        print("\nFAILED (below required coverage)")
        print("-" * 80)
        for r in failed:
            gap = float(r["required"]) - float(r["coverage"])
            print(f"  {r['path']}")
            print(f"    Coverage: {r['coverage']:.1f}% (required: {r['required']}%)")
            print(f"    Gap: {gap:.1f}% | Reason: {r['reason']}")
            print()

    if missing:
        print("\nMISSING (not found in coverage report)")
        print("-" * 80)
        for r in missing:
            print(f"  {r['path']}")
            print(f"    {r['message']}")
            print(f"    Reason: {r['reason']}")
            print()

    if passed:
        print("\nPASSED")
        print("-" * 80)
        for r in passed:
            print(f"  {r['path']}: {r['coverage']:.1f}% (required: {r['required']}%)")

    print("\n" + "=" * 80)
    print(f"SUMMARY: {len(passed)} passed, {len(failed)} failed, {len(missing)} missing")
    print("=" * 80)

    if failed or missing:
        print("\nCritical path coverage check FAILED.")
        return False
    print("\nAll critical paths meet minimum coverage.")
    return True


def main() -> None:
    root = _repo_root()
    data = load_coverage_data(root)
    results = check_critical_coverage(data, root)
    ok = print_results(results)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
