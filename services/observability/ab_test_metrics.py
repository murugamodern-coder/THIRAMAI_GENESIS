"""
A/B test metrics for the PolicyEngine ↔ legacy decision_brain migration.

Both variants persist a ``LearningLog`` row tagged via ``source_type`` (either
``"policy_engine"`` or ``"legacy_brain"``). Confidence and reward live inside
``outcome_json`` because those columns do not exist on ``LearningLog``.

The metrics exporter is read-only; it never writes back to the table.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import LearningLog

_LOG = logging.getLogger(__name__)

POLICY_VARIANT = "policy_engine"
LEGACY_VARIANT = "legacy_brain"

# Minimum sample size per variant before we recommend a migration step.
MIN_SAMPLES_PER_VARIANT = 100


@dataclass
class VariantMetrics:
    total_decisions: int
    resolved_decisions: int
    success_rate: float
    avg_confidence: float
    avg_reward: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_decisions": int(self.total_decisions),
            "resolved_decisions": int(self.resolved_decisions),
            "success_rate": round(float(self.success_rate), 4),
            "avg_confidence": round(float(self.avg_confidence), 4),
            "avg_reward": round(float(self.avg_reward), 4),
        }


@dataclass
class Comparison:
    success_rate_lift_pct: float
    policy_better: bool
    sample_size_policy: int
    sample_size_legacy: int
    enough_data: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "success_rate_lift_pct": round(float(self.success_rate_lift_pct), 2),
            "policy_better": bool(self.policy_better),
            "sample_size_policy": int(self.sample_size_policy),
            "sample_size_legacy": int(self.sample_size_legacy),
            "enough_data": bool(self.enough_data),
        }


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _row_confidence(row: LearningLog) -> float | None:
    payload = row.outcome_json
    if isinstance(payload, dict):
        v = payload.get("confidence")
        if isinstance(v, (int, float)):
            return float(v)
    return None


def _row_reward(row: LearningLog) -> float | None:
    payload = row.outcome_json
    if isinstance(payload, dict):
        v = payload.get("reward")
        if isinstance(v, (int, float)):
            return float(v)
    return None


def _calculate_variant_metrics(rows: list[LearningLog]) -> VariantMetrics:
    if not rows:
        return VariantMetrics(0, 0, 0.0, 0.0, 0.0)

    rewards: list[float] = []
    confidences: list[float] = []
    successes = 0
    resolved = 0

    for row in rows:
        c = _row_confidence(row)
        if c is not None:
            confidences.append(c)
        r = _row_reward(row)
        if r is not None:
            rewards.append(r)
            resolved += 1
            if (row.success is True) or (row.success is None and r > 0):
                successes += 1
        elif row.success is True:
            successes += 1
            resolved += 1
        elif row.success is False:
            resolved += 1

    success_rate = (successes / resolved) if resolved else 0.0
    avg_confidence = (sum(confidences) / len(confidences)) if confidences else 0.0
    avg_reward = (sum(rewards) / len(rewards)) if rewards else 0.0

    return VariantMetrics(
        total_decisions=len(rows),
        resolved_decisions=resolved,
        success_rate=success_rate,
        avg_confidence=avg_confidence,
        avg_reward=avg_reward,
    )


def _compare(policy: VariantMetrics, legacy: VariantMetrics) -> Comparison:
    if legacy.success_rate > 0:
        lift = ((policy.success_rate - legacy.success_rate) / legacy.success_rate) * 100.0
    elif policy.success_rate > 0:
        lift = 100.0  # legacy was 0, policy moved off zero
    else:
        lift = 0.0
    enough = (
        policy.total_decisions >= MIN_SAMPLES_PER_VARIANT
        and legacy.total_decisions >= MIN_SAMPLES_PER_VARIANT
    )
    return Comparison(
        success_rate_lift_pct=lift,
        policy_better=policy.success_rate > legacy.success_rate,
        sample_size_policy=policy.total_decisions,
        sample_size_legacy=legacy.total_decisions,
        enough_data=enough,
    )


class ABTestMetrics:
    """Read-only reporter over ``learning_logs`` rows tagged by ``source_type``."""

    def get_metrics(self, days: int = 7) -> dict[str, Any]:
        cutoff = _now_utc() - timedelta(days=max(1, int(days)))
        factory = get_session_factory()
        if factory is None:
            return {
                "ok": False,
                "error": "database_unavailable",
                "period_days": int(days),
                "policy_engine": VariantMetrics(0, 0, 0.0, 0.0, 0.0).as_dict(),
                "legacy_brain": VariantMetrics(0, 0, 0.0, 0.0, 0.0).as_dict(),
                "comparison": Comparison(0.0, False, 0, 0, False).as_dict(),
            }

        try:
            with factory() as session:
                stmt = (
                    select(LearningLog)
                    .where(LearningLog.created_at >= cutoff)
                    .where(
                        LearningLog.source_type.in_((POLICY_VARIANT, LEGACY_VARIANT))
                    )
                    .order_by(LearningLog.created_at.desc())
                    .limit(20_000)
                )
                rows = list(session.execute(stmt).scalars().all())
        except Exception as exc:
            _LOG.warning("ab_test_metrics.get_metrics query failed: %s", exc)
            return {
                "ok": False,
                "error": str(exc),
                "period_days": int(days),
                "policy_engine": VariantMetrics(0, 0, 0.0, 0.0, 0.0).as_dict(),
                "legacy_brain": VariantMetrics(0, 0, 0.0, 0.0, 0.0).as_dict(),
                "comparison": Comparison(0.0, False, 0, 0, False).as_dict(),
            }

        policy_rows = [r for r in rows if r.source_type == POLICY_VARIANT]
        legacy_rows = [r for r in rows if r.source_type == LEGACY_VARIANT]
        policy = _calculate_variant_metrics(policy_rows)
        legacy = _calculate_variant_metrics(legacy_rows)
        comparison = _compare(policy, legacy)

        return {
            "ok": True,
            "period_days": int(days),
            "policy_engine": policy.as_dict(),
            "legacy_brain": legacy.as_dict(),
            "comparison": comparison.as_dict(),
        }

    def print_report(self, *, days: int = 7) -> dict[str, Any]:
        metrics = self.get_metrics(days=days)
        print("=" * 60)
        print(f"A/B TEST REPORT — LAST {metrics['period_days']} DAYS")
        print("=" * 60)
        if not metrics.get("ok"):
            print(f"\nError: {metrics.get('error')}")
            print("=" * 60)
            return metrics

        for key in ("policy_engine", "legacy_brain"):
            print(f"\n{key.upper()}:")
            for k, v in metrics[key].items():
                print(f"  {k}: {v}")

        print("\nCOMPARISON:")
        for k, v in metrics["comparison"].items():
            print(f"  {k}: {v}")
        print("\n" + "=" * 60)

        comp = metrics["comparison"]
        if comp["enough_data"]:
            if comp["policy_better"]:
                print("RECOMMENDATION: migrate to PolicyEngine.")
                print(f"  success_rate_lift_pct = {comp['success_rate_lift_pct']:.2f}")
            else:
                print("RECOMMENDATION: keep legacy.")
                print("  PolicyEngine has not yet beaten the legacy success rate.")
        else:
            print(
                "RECOMMENDATION: collect more data "
                f"(need {MIN_SAMPLES_PER_VARIANT}+ decisions per variant)."
            )
        print("=" * 60)
        return metrics


def main() -> None:
    ABTestMetrics().print_report(days=7)


if __name__ == "__main__":  # pragma: no cover - manual run
    main()


__all__ = [
    "ABTestMetrics",
    "Comparison",
    "LEGACY_VARIANT",
    "MIN_SAMPLES_PER_VARIANT",
    "POLICY_VARIANT",
    "VariantMetrics",
]
