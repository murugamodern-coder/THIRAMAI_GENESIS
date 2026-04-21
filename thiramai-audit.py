from __future__ import annotations

import json
from pathlib import Path


def _load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def main() -> int:
    root = Path(__file__).resolve().parent
    audit_file = root / "logs" / "audit_trail.jsonl"
    rows = _load_rows(audit_file)
    total = len(rows)
    allowed = 0
    blocked = 0
    error = 0
    high_risk = 0
    for row in rows:
        decision = row.get("policy_decision") if isinstance(row.get("policy_decision"), dict) else {}
        if decision.get("allow") is True:
            allowed += 1
        if str(row.get("execution_status", "")).lower() == "blocked":
            blocked += 1
        if str(row.get("execution_status", "")).lower() == "error":
            error += 1
        if str(row.get("risk_level", "low")).lower() == "high":
            high_risk += 1

    print("THIRAMAI Security Audit Summary")
    print("=" * 34)
    print(f"{'Audit file':<24} {audit_file}")
    print(f"{'Total records':<24} {total}")
    print(f"{'Policy allowed':<24} {allowed}")
    print(f"{'Policy blocks':<24} {blocked}")
    print(f"{'Execution errors':<24} {error}")
    print(f"{'High-risk tasks':<24} {high_risk}")
    if total > 0:
        block_rate = (blocked / total) * 100.0
        print(f"{'Block rate':<24} {block_rate:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
