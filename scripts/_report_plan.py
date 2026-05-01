"""Quick summariser for analysis_plan.json (used to display findings to humans)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
plan = json.loads((REPO / "analysis_plan.json").read_text(encoding="utf-8"))

print("=" * 78)
print("SUMMARY")
print("=" * 78)
print(f"services modules                  : {plan['services_module_count']}")
print(f"prefix groups with >=2 modules     : {plan['groups_with_duplicates']}")
print(f"modules in duplicate groups        : {plan['modules_in_duplicate_groups']}")
print(f"SAFE-removable now (no importers)  : {plan['safe_removable_modules']}")
print(f"estimated post-consolidation total : {plan['estimated_post_consolidation_count']}")
print()

groups = sorted(plan["groups"], key=lambda g: -g["module_count"])

print(f"TOP-15 PREFIX GROUPS BY SIZE")
print("-" * 78)
print(f"{'prefix':14s} {'n':>3s} {'safe_rm':>8s} {'risky':>6s} {'blocked':>8s}  hint")
for g in groups[:15]:
    risky = sum(1 for m in g["members"] if m["consolidation"] == "RISKY")
    print(
        f"{g['prefix']:14s} "
        f"{g['module_count']:>3d} "
        f"{len(g['safe_to_remove_now']):>8d} "
        f"{risky:>6d} "
        f"{len(g['blocked_keep']):>8d}  "
        f"{g['target_hint'] or '-'}"
    )
print()

print("DETAILED FINDINGS FOR HIGH-PRIORITY GROUPS (decision, goal, autonomy, autonomous, jarvis)")
print("-" * 78)
priority = {"decision", "goal", "autonomy", "autonomous", "jarvis", "execution", "self", "research"}
for g in groups:
    if g["prefix"] not in priority:
        continue
    print()
    print(f"PREFIX '{g['prefix']}'  ({g['module_count']} modules)  hint -> {g['target_hint']}")
    for m in g["members"]:
        print(f"  [{m['consolidation']:7s}] {m['path']:60s}  L={m['lines']:>4d}  importers={m['importer_count']}")
    if g["safe_to_remove_now"]:
        print(f"  -- safe-removable: {g['safe_to_remove_now']}")

print()
print("ALL SAFE-REMOVABLE MODULES (would be deleted by Phase-1 consolidation):")
print("-" * 78)
all_safe: list[str] = []
for g in groups:
    all_safe.extend(g["safe_to_remove_now"])
for path in sorted(all_safe):
    print(f"  {path}")
print(f"\nTotal: {len(all_safe)}")
