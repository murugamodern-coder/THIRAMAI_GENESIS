"""Safe consolidator for duplicate service modules.

Reads ``analysis_plan.json`` (produced by ``scripts/analyze_duplicates.py``) and
executes only the changes that are guaranteed safe:

* **Phase 1 - SAFE prune.** Modules whose ``consolidation`` classification is
  ``SAFE`` (zero live importers, <200 lines) AND not in the protect-list are
  copied to ``backups/consolidation/<timestamp>/`` and then removed.
* **Phase 2 - RISKY checklist.** For every ``RISKY`` module the tool prints a
  one-screen migration checklist (importers, suggested target, command to run
  once callers are migrated). It does **not** modify these files.
* **Phase 3 - BLOCKED list.** Modules with >2 importers are listed for manual
  refactor. The tool refuses to touch them.

Defaults to dry-run; pass ``--execute`` to actually make changes. Every change
is logged to ``backups/consolidation/<timestamp>/changelog.txt``.

Re-running ``scripts/analyze_duplicates.py`` after a consolidation pass is the
correct way to discover newly-safe modules: as you migrate RISKY callers, the
modules drop into the SAFE bucket and the next pass can prune them.

Usage::

    python scripts/consolidate_modules.py                  # dry-run report
    python scripts/consolidate_modules.py --plan p.json    # custom plan path
    python scripts/consolidate_modules.py --execute        # actually delete
    python scripts/consolidate_modules.py --execute --include-review  # also \
        prune REVIEW (zero importers, big files) - extra caution required
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


# Modules that are intentionally opt-in (no callers today, by design).
# The consolidator will refuse to delete any of these even if classified SAFE.
PROTECTED_MODULES = {
    # FastAPI lifecycle wiring for the PolicyEngine - opt-in via app.py.
    "services/policy_engine_lifecycle.py",
    # Comparison & migration helpers for the live A/B rollout.
    "services/decision_router.py",
    "services/decision_brain_v2.py",
    # Newly-shipped observability stack (zero importers expected; auto-wired
    # via lazy init).
    "services/observability/business_metrics.py",
    "services/observability/decision_metrics.py",
    "services/observability/ab_test_metrics.py",
    "services/health_service.py",
    # PolicyEngine + persistence are the consolidation *target*, not source.
    "services/policy_engine.py",
    "services/policy_engine_persistence.py",
}


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# Plan loader
# ---------------------------------------------------------------------------


def load_plan(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(
            f"plan file not found: {path}\n"
            f"run scripts/analyze_duplicates.py --out {path.name} first"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def collect_safe(plan: dict[str, Any], include_review: bool) -> list[dict[str, Any]]:
    """All modules whose classification is SAFE (and optionally REVIEW)."""
    out: list[dict[str, Any]] = []
    accept = {"SAFE"}
    if include_review:
        accept.add("REVIEW")
    for group in plan.get("groups", []):
        for member in group.get("members", []):
            if member["consolidation"] in accept:
                out.append(member)
    return out


def collect_risky(plan: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for group in plan.get("groups", []):
        for member in group.get("members", []):
            if member["consolidation"] == "RISKY":
                out.append(dict(member, _prefix=group["prefix"], _target_hint=group.get("target_hint")))
    return out


def collect_blocked(plan: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for group in plan.get("groups", []):
        for member in group.get("members", []):
            if member["consolidation"] == "BLOCKED":
                out.append(dict(member, _prefix=group["prefix"]))
    return out


# ---------------------------------------------------------------------------
# Backup + delete
# ---------------------------------------------------------------------------


class Consolidator:
    def __init__(self, *, dry_run: bool, plan: dict[str, Any], include_review: bool) -> None:
        self.dry_run = dry_run
        self.plan = plan
        self.include_review = include_review
        self.stamp = _now_stamp()
        self.backup_dir = REPO_ROOT / "backups" / "consolidation" / self.stamp
        self.changelog: list[str] = []

    def _norm(self, p: str) -> str:
        return p.replace("\\", "/")

    # -- phase 1 ---------------------------------------------------------

    def phase1_safe_prune(self) -> tuple[int, int]:
        """Return ``(deleted, protected)``."""
        candidates = collect_safe(self.plan, self.include_review)
        deleted = 0
        protected = 0

        if not candidates:
            print("[phase 1] nothing classified SAFE - skipping")
            return (0, 0)

        if not self.dry_run:
            self.backup_dir.mkdir(parents=True, exist_ok=True)

        queued = 0
        for module in candidates:
            rel = self._norm(module["path"])
            full = REPO_ROOT / rel
            if rel in PROTECTED_MODULES:
                protected += 1
                print(f"[phase 1] PROTECTED  skip   {rel}  (in PROTECTED_MODULES)")
                self.changelog.append(f"protected: {rel}")
                continue
            if not full.is_file():
                print(f"[phase 1] MISSING    skip   {rel}  (file not on disk)")
                continue
            print(
                f"[phase 1] {'DRY-RUN ' if self.dry_run else 'DELETE  '} {rel}  "
                f"L={module['lines']}  importers={module['importer_count']}  ({module['consolidation']})"
            )
            self.changelog.append(
                f"phase1 {'dryrun' if self.dry_run else 'deleted'}: {rel}  "
                f"classification={module['consolidation']}  lines={module['lines']}"
            )
            queued += 1
            if self.dry_run:
                continue
            backup_path = self.backup_dir / Path(rel).name
            try:
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(full, backup_path)
                full.unlink()
                deleted += 1
            except Exception as exc:  # pragma: no cover - filesystem edge
                print(f"          ERROR while removing {rel}: {exc}")
                self.changelog.append(f"error removing {rel}: {exc}")

        return (queued if self.dry_run else deleted), protected

    # -- phase 2 ---------------------------------------------------------

    def phase2_risky_checklist(self) -> int:
        risky = collect_risky(self.plan)
        if not risky:
            print("[phase 2] nothing classified RISKY")
            return 0
        print()
        print("[phase 2] RISKY modules - migrate the listed callers, then re-run analyze:")
        print("-" * 78)
        for m in risky:
            target = m.get("_target_hint") or "(no canonical target hinted)"
            print(f"  {m['path']}  L={m['lines']}  importers={m['importer_count']}  prefix='{m['_prefix']}'")
            print(f"     suggested target after migration: {target}")
            for imp in m["importers"]:
                print(f"       - migrate caller: {imp}")
        return len(risky)

    # -- phase 3 ---------------------------------------------------------

    def phase3_blocked_list(self) -> int:
        blocked = collect_blocked(self.plan)
        if not blocked:
            print("[phase 3] nothing classified BLOCKED")
            return 0
        print()
        print("[phase 3] BLOCKED modules (>2 callers) - require manual refactor; not touched:")
        print("-" * 78)
        for m in blocked:
            print(f"  KEEP  {m['path']}  L={m['lines']}  importers={m['importer_count']}  prefix='{m['_prefix']}'")
        return len(blocked)

    # -- run -------------------------------------------------------------

    def run(self) -> int:
        mode = "DRY RUN" if self.dry_run else "EXECUTE"
        print("=" * 78)
        print(f"THIRAMAI MODULE CONSOLIDATOR ({mode})  stamp={self.stamp}")
        print(f"include_review={self.include_review}")
        if not self.dry_run:
            print(f"backup dir: {self.backup_dir.relative_to(REPO_ROOT)}")
        print("=" * 78)

        deleted, protected = self.phase1_safe_prune()
        risky_count = self.phase2_risky_checklist()
        blocked_count = self.phase3_blocked_list()

        print()
        print("=" * 78)
        print(
            f"summary: phase1 {'queued' if self.dry_run else 'deleted'}={deleted}  "
            f"protected={protected}  risky={risky_count}  blocked={blocked_count}"
        )
        if self.dry_run:
            print("DRY RUN - no changes made. Re-run with --execute to apply phase 1.")
        else:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            (self.backup_dir / "changelog.txt").write_text(
                "\n".join(self.changelog) + "\n", encoding="utf-8"
            )
            print(f"changelog: {(self.backup_dir / 'changelog.txt').relative_to(REPO_ROOT)}")
        print("=" * 78)
        return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--plan",
        default="analysis_plan.json",
        help="path to JSON output of analyze_duplicates.py (default: analysis_plan.json)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="actually back up and delete SAFE modules. Without this flag the script is dry-run.",
    )
    parser.add_argument(
        "--include-review",
        action="store_true",
        help="also prune modules classified REVIEW (zero importers but >=200 lines). Use with caution.",
    )
    args = parser.parse_args(argv)

    plan_path = Path(args.plan)
    if not plan_path.is_absolute():
        plan_path = REPO_ROOT / plan_path
    plan = load_plan(plan_path)

    cons = Consolidator(
        dry_run=not args.execute,
        plan=plan,
        include_review=args.include_review,
    )
    return cons.run()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
