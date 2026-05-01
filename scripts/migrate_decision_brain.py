"""
Runbook script for the decision_brain → PolicyEngine migration.

The script does **not** mutate environment variables of running processes
(``os.environ`` writes only affect the current Python process and would silently
do nothing for a deployed gunicorn / worker container). Instead, each phase:

1. validates the current state via :class:`ABTestMetrics`,
2. prints the exact env-var changes the operator must apply, and
3. (optionally) writes those values into a dotenv file via ``--apply-env-file``.

Examples
--------

    # Print current A/B report
    python scripts/migrate_decision_brain.py --check-metrics

    # Phase 1: enable 50/50 A/B test
    python scripts/migrate_decision_brain.py --phase1
    python scripts/migrate_decision_brain.py --phase1 --apply-env-file .env

    # Phase 2: ramp PolicyEngine to 75% (requires enough data + better metrics)
    python scripts/migrate_decision_brain.py --phase2

    # Phase 3: full cutover
    python scripts/migrate_decision_brain.py --phase3
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.observability.ab_test_metrics import (  # noqa: E402
    ABTestMetrics,
    MIN_SAMPLES_PER_VARIANT,
)


PHASE_1_VARS = {"DECISION_AB_TEST": "true", "POLICY_ENGINE_PCT": "50"}
PHASE_2_VARS = {"DECISION_AB_TEST": "true", "POLICY_ENGINE_PCT": "75"}
PHASE_3_VARS = {"DECISION_AB_TEST": "false", "POLICY_ENGINE_PCT": "100"}


def _print_env_block(values: dict[str, str]) -> None:
    print("\nApply these to your runtime environment (.env / compose / k8s):")
    for k, v in values.items():
        print(f"  {k}={v}")


def _apply_env_file(path: Path, values: dict[str, str]) -> None:
    """Insert / replace each ``KEY=VALUE`` pair in ``path``. Creates a backup."""

    if path.exists():
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copyfile(path, backup)
        print(f"Backed up existing env file to {backup}")
        original_lines = path.read_text(encoding="utf-8").splitlines()
    else:
        original_lines = []

    remaining = dict(values)
    new_lines: list[str] = []
    for line in original_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in remaining:
            new_lines.append(f"{key}={remaining.pop(key)}")
        else:
            new_lines.append(line)

    for k, v in remaining.items():
        new_lines.append(f"{k}={v}")

    path.write_text("\n".join(new_lines).rstrip("\n") + "\n", encoding="utf-8")
    print(f"Wrote {len(values)} key(s) to {path}")


def _print_metrics(days: int) -> dict:
    return ABTestMetrics().print_report(days=days)


def _gate_on_metrics(days: int) -> tuple[bool, dict]:
    metrics = ABTestMetrics().get_metrics(days=days)
    comp = metrics.get("comparison", {})
    if not metrics.get("ok"):
        print(f"Metrics unavailable: {metrics.get('error')}")
        return False, metrics
    if not comp.get("enough_data"):
        print(
            "Not enough data yet. "
            f"Need {MIN_SAMPLES_PER_VARIANT}+ decisions per variant. "
            f"Got policy={comp.get('sample_size_policy')} legacy={comp.get('sample_size_legacy')}"
        )
        return False, metrics
    if not comp.get("policy_better"):
        print(
            "PolicyEngine is not outperforming legacy yet. "
            f"success_rate_lift_pct={comp.get('success_rate_lift_pct')}."
        )
        return False, metrics
    return True, metrics


def _phase(
    name: str,
    *,
    description: str,
    values: dict[str, str],
    apply_env_file: Path | None,
    gate_days: int | None,
) -> int:
    print(f"\n{name}: {description}")
    if gate_days is not None:
        ok, _ = _gate_on_metrics(gate_days)
        if not ok:
            print("Aborting. Resolve the gate above before re-running.")
            return 2
    _print_env_block(values)
    if apply_env_file is not None:
        _apply_env_file(apply_env_file, values)
    print(f"\n{name} ready. Restart the API + workers to pick up the new env values.")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="migrate_decision_brain",
        description="Runbook for the decision_brain → PolicyEngine migration.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--check-metrics",
        action="store_true",
        help="Print the current A/B test report and exit.",
    )
    group.add_argument(
        "--phase1",
        action="store_true",
        help="Enable 50/50 A/B routing (PolicyEngine vs legacy).",
    )
    group.add_argument(
        "--phase2",
        action="store_true",
        help="Ramp PolicyEngine to 75% (requires positive A/B gate).",
    )
    group.add_argument(
        "--phase3",
        action="store_true",
        help="Full cutover: 100% PolicyEngine, A/B disabled.",
    )

    parser.add_argument(
        "--apply-env-file",
        type=Path,
        help="Optionally write the recommended values into a dotenv file in place.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Window for --check-metrics (default 7).",
    )
    parser.add_argument(
        "--gate-days",
        type=int,
        default=None,
        help="Override the A/B-gate window for --phase2 / --phase3.",
    )
    return parser


def _resolve_gate_days(args: argparse.Namespace, default: int) -> int:
    return int(args.gate_days) if args.gate_days is not None else int(default)


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.check_metrics:
        _print_metrics(days=args.days)
        return 0

    if args.phase1:
        return _phase(
            "PHASE 1",
            description="enable 50/50 A/B routing",
            values=PHASE_1_VARS,
            apply_env_file=args.apply_env_file,
            gate_days=None,
        )
    if args.phase2:
        return _phase(
            "PHASE 2",
            description="ramp PolicyEngine to 75%",
            values=PHASE_2_VARS,
            apply_env_file=args.apply_env_file,
            gate_days=_resolve_gate_days(args, default=7),
        )
    if args.phase3:
        return _phase(
            "PHASE 3",
            description="full cutover to PolicyEngine",
            values=PHASE_3_VARS,
            apply_env_file=args.apply_env_file,
            gate_days=_resolve_gate_days(args, default=3),
        )
    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover - manual run
    raise SystemExit(main())
