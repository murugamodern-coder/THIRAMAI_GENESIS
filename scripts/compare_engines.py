"""
Pretty A/B comparison report for PolicyEngine vs the legacy decision_brain.

Reuses :class:`services.observability.ab_test_metrics.ABTestMetrics` for the
core stats and adds:

* Per-variant action distribution (top N) so operators can see *what kinds of
  decisions* each engine is making — a 30% policy lift means little if the
  policy is just learning to ``hold`` everything.
* Reward lift in addition to success-rate lift (the original report only had
  success rate).
* ASCII-only output so it renders cleanly on Windows console without Unicode
  escapes.

Usage::

    python scripts/compare_engines.py --days 7
    python scripts/compare_engines.py --days 1 --top-actions 3
    python scripts/compare_engines.py --days 7 --json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import select  # noqa: E402

from core.database import get_session_factory  # noqa: E402
from core.db.models import LearningLog  # noqa: E402
from services.observability.ab_test_metrics import (  # noqa: E402
    ABTestMetrics,
    LEGACY_VARIANT,
    POLICY_VARIANT,
)


def _action_distribution(rows: list[LearningLog]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        action = (row.action_type or "unknown").strip() or "unknown"
        counts[action] = counts.get(action, 0) + 1
    return counts


def _reward_average(rows: list[LearningLog]) -> tuple[float, int]:
    rewards: list[float] = []
    for row in rows:
        payload = row.outcome_json
        if isinstance(payload, dict):
            v = payload.get("reward")
            if isinstance(v, (int, float)):
                rewards.append(float(v))
    return (sum(rewards) / len(rewards), len(rewards)) if rewards else (0.0, 0)


def _fetch_action_breakdown(days: int) -> dict[str, dict[str, dict[str, int]]]:
    factory = get_session_factory()
    if factory is None:
        return {"policy_engine": {"actions": {}}, "legacy_brain": {"actions": {}}}
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))
    try:
        with factory() as session:
            stmt = (
                select(LearningLog)
                .where(LearningLog.created_at >= cutoff)
                .where(LearningLog.source_type.in_((POLICY_VARIANT, LEGACY_VARIANT)))
                .order_by(LearningLog.created_at.desc())
                .limit(20_000)
            )
            rows = list(session.execute(stmt).scalars().all())
    except Exception as exc:
        print(f"WARN: action breakdown query failed: {exc}", file=sys.stderr)
        return {"policy_engine": {"actions": {}}, "legacy_brain": {"actions": {}}}

    policy_rows = [r for r in rows if r.source_type == POLICY_VARIANT]
    legacy_rows = [r for r in rows if r.source_type == LEGACY_VARIANT]
    policy_avg_reward, policy_resolved = _reward_average(policy_rows)
    legacy_avg_reward, legacy_resolved = _reward_average(legacy_rows)
    return {
        "policy_engine": {
            "actions": _action_distribution(policy_rows),
            "avg_reward": policy_avg_reward,
            "resolved": policy_resolved,
        },
        "legacy_brain": {
            "actions": _action_distribution(legacy_rows),
            "avg_reward": legacy_avg_reward,
            "resolved": legacy_resolved,
        },
    }


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _print_variant(label: str, summary: dict[str, Any], breakdown: dict[str, Any], top: int) -> None:
    print(f"\n{label}:")
    total = int(summary.get("total_decisions", 0))
    resolved = int(summary.get("resolved_decisions", 0))
    print(f"  total_decisions:    {total}")
    print(f"  resolved_decisions: {resolved}")
    print(f"  success_rate:       {_percent(float(summary.get('success_rate', 0.0)))}")
    print(f"  avg_confidence:     {float(summary.get('avg_confidence', 0.0)):.3f}")
    print(f"  avg_reward:         {float(summary.get('avg_reward', 0.0)):+.3f}")

    actions = breakdown.get("actions") or {}
    if total and actions:
        print("  top_actions:")
        sorted_actions = sorted(actions.items(), key=lambda kv: kv[1], reverse=True)
        for action, count in sorted_actions[: max(1, int(top))]:
            pct = (count / total) * 100.0
            print(f"    {action:<20} {count:>5}  ({pct:5.1f}%)")
    elif total:
        print("  top_actions:        (no action_type recorded)")


def _reward_lift(policy: float, legacy: float) -> float:
    if abs(legacy) < 1e-9:
        if abs(policy) < 1e-9:
            return 0.0
        return 100.0 if policy > 0 else -100.0
    return ((policy - legacy) / abs(legacy)) * 100.0


def build_report(days: int, top: int) -> dict[str, Any]:
    summary = ABTestMetrics().get_metrics(days=days)
    breakdown = _fetch_action_breakdown(days)
    return {
        "days": int(days),
        "summary": summary,
        "breakdown": breakdown,
        "top_actions": int(top),
    }


def print_report(report: dict[str, Any]) -> None:
    days = int(report["days"])
    top = int(report["top_actions"])
    summary = report["summary"]
    breakdown = report["breakdown"]

    print("=" * 70)
    print(f"ENGINE COMPARISON REPORT - last {days} day(s)")
    print("=" * 70)

    if not summary.get("ok"):
        print(f"\nERROR: {summary.get('error')}")
        print("=" * 70)
        return

    _print_variant("POLICY ENGINE", summary["policy_engine"], breakdown["policy_engine"], top)
    _print_variant("LEGACY BRAIN", summary["legacy_brain"], breakdown["legacy_brain"], top)

    comp = summary["comparison"]
    reward_lift_pct = _reward_lift(
        float(breakdown["policy_engine"].get("avg_reward", 0.0)),
        float(breakdown["legacy_brain"].get("avg_reward", 0.0)),
    )

    print("\nCOMPARISON:")
    print(f"  success_rate_lift_pct: {float(comp['success_rate_lift_pct']):+.2f}%")
    print(f"  reward_lift_pct:       {reward_lift_pct:+.2f}%")
    print(f"  policy_better:         {comp['policy_better']}")
    print(f"  enough_data:           {comp['enough_data']}")
    print(f"  sample_size_policy:    {comp['sample_size_policy']}")
    print(f"  sample_size_legacy:    {comp['sample_size_legacy']}")

    print("\n" + "=" * 70)
    if comp["enough_data"]:
        if comp["policy_better"]:
            print("RECOMMENDATION: increase PolicyEngine percentage (run --phase2 / --phase3).")
        else:
            print("RECOMMENDATION: hold current split. Investigate before ramping further.")
    else:
        print("RECOMMENDATION: collect more data (50-100+ decisions per variant).")
    print("=" * 70)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="compare_engines")
    parser.add_argument("--days", type=int, default=7, help="Lookback window (default 7).")
    parser.add_argument(
        "--top-actions",
        type=int,
        default=5,
        help="How many top actions to show per variant (default 5).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the full report as JSON instead of the human-readable view.",
    )
    args = parser.parse_args(argv)

    report = build_report(days=args.days, top=args.top_actions)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print_report(report)
    return 0


if __name__ == "__main__":  # pragma: no cover - manual run
    raise SystemExit(main())
