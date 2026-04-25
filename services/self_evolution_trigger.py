"""
Self-Evolution Phase 1: trigger-based watcher that opens self-coder proposals.

Hourly job. Three trigger families:

1. ``low_accuracy`` — predictor accuracy below threshold for the last N days
2. ``recurring_error`` — same error message appears K+ times in recent logs
3. ``metric_decline`` — a business metric declines D days straight

Every detected condition writes a row into ``evolution_triggers`` (status=``proposed``)
and is **owner-approved before** ``services.self_coder_agent.run_pipeline`` is called.

Nothing here ever runs the self-coder pipeline directly. The owner-only API
``POST /security/evolution/triggers/{id}/approve`` (Phase 2) is what dispatches.

Public API
----------
- ``check_and_trigger(organization_id=None)`` — main hourly entry point
- ``propose_improvement(target, reason, proposed_change, *, trigger_type, evidence)``
- ``recent_triggers(limit=20, status=None)``
- ``get_recurring_errors(min_count=10, days=3)``
- ``get_declining_metrics(days=3)``
"""

from __future__ import annotations

import logging
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import EvolutionTrigger, LearningLog, OpportunityProfitLog
from services.ml import outcome_predictor

_LOG = logging.getLogger(__name__)

DEFAULT_ACCURACY_THRESHOLD = float(os.getenv("THIRAMAI_EVOLUTION_ACCURACY_THRESHOLD") or "0.60")
DEFAULT_ACCURACY_WINDOW_DAYS = int(os.getenv("THIRAMAI_EVOLUTION_ACCURACY_WINDOW_DAYS") or "7")
DEFAULT_ERROR_MIN_COUNT = int(os.getenv("THIRAMAI_EVOLUTION_ERROR_MIN_COUNT") or "10")
DEFAULT_ERROR_WINDOW_DAYS = int(os.getenv("THIRAMAI_EVOLUTION_ERROR_WINDOW_DAYS") or "3")
DEFAULT_METRIC_DECLINE_DAYS = int(os.getenv("THIRAMAI_EVOLUTION_METRIC_DECLINE_DAYS") or "3")

_TRIGGER_LOW_ACCURACY = "low_accuracy"
_TRIGGER_RECURRING_ERROR = "recurring_error"
_TRIGGER_METRIC_DECLINE = "metric_decline"

# Cooldown so we don't spam triggers when a condition persists for many hours.
_TRIGGER_COOLDOWN_HOURS = int(os.getenv("THIRAMAI_EVOLUTION_TRIGGER_COOLDOWN_HOURS") or "12")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _factory_or_none():
    try:
        return get_session_factory()
    except Exception as exc:
        _LOG.debug("self_evolution_trigger session factory unavailable: %s", exc)
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------


def _has_recent_trigger(*, trigger_type: str, target: str, hours: int) -> bool:
    factory = _factory_or_none()
    if factory is None:
        return False
    cutoff = _now() - timedelta(hours=max(1, int(hours)))
    with factory() as session:
        row = (
            session.execute(
                select(EvolutionTrigger.id)
                .where(
                    EvolutionTrigger.trigger_type == str(trigger_type),
                    EvolutionTrigger.target == str(target),
                    EvolutionTrigger.created_at >= cutoff,
                    EvolutionTrigger.status.in_(("proposed", "approved", "applied")),
                )
                .order_by(EvolutionTrigger.created_at.desc())
                .limit(1)
            )
            .first()
        )
    return row is not None


# ---------------------------------------------------------------------------
# Public: persist a proposal
# ---------------------------------------------------------------------------


def propose_improvement(
    *,
    target: str,
    reason: str,
    proposed_change: str,
    trigger_type: str,
    evidence: dict[str, Any] | None = None,
    cooldown_hours: int = _TRIGGER_COOLDOWN_HOURS,
) -> dict[str, Any]:
    """Insert a row into ``evolution_triggers`` (status=``proposed``).

    Owner-only API approval is what eventually calls
    ``services.self_coder_agent.run_pipeline``. Nothing in this function executes code.
    """
    if _has_recent_trigger(
        trigger_type=trigger_type, target=target, hours=int(cooldown_hours)
    ):
        return {"ok": False, "skipped": True, "reason": "cooldown_active", "target": target}
    factory = _factory_or_none()
    if factory is None:
        return {"ok": False, "skipped": True, "reason": "no_db", "target": target}
    with factory() as session:
        row = EvolutionTrigger(
            trigger_type=str(trigger_type)[:64],
            target=str(target)[:255],
            reason=str(reason)[:4_000],
            proposed_change=str(proposed_change)[:4_000],
            status="proposed",
            evidence=dict(evidence or {}),
        )
        session.add(row)
        session.commit()
        rid = int(row.id)
    _LOG.info(
        "self_evolution_trigger.proposed type=%s target=%s id=%s",
        trigger_type,
        target,
        rid,
    )
    return {"ok": True, "id": rid, "trigger_type": trigger_type, "target": target}


# ---------------------------------------------------------------------------
# Trigger 1: low accuracy
# ---------------------------------------------------------------------------


def _check_low_accuracy(*, threshold: float, window_days: int) -> dict[str, Any] | None:
    info = outcome_predictor.get_recent_accuracy(days=window_days)
    if not info.get("ok"):
        return None
    accuracy = float(info.get("accuracy") or 0.0)
    samples = int(info.get("samples") or 0)
    # Need at least a few samples before we cry wolf.
    if samples < 25:
        return None
    if accuracy >= float(threshold):
        return None
    return {
        "trigger_type": _TRIGGER_LOW_ACCURACY,
        "target": "services/ml/outcome_predictor.py",
        "reason": f"Predictor accuracy {accuracy:.0%} below threshold {threshold:.0%} over last {window_days} days (n={samples}).",
        "proposed_change": (
            "Improve feature engineering or switch algorithm in services/ml/outcome_predictor.py: "
            "consider adding more context features (recent revenue trend, time-since-last-success), "
            "or experimenting with gradient boosting / class-rebalancing."
        ),
        "evidence": {
            "accuracy": round(accuracy, 4),
            "samples": samples,
            "threshold": float(threshold),
            "window_days": int(window_days),
            "source": str(info.get("source") or "unknown"),
        },
    }


# ---------------------------------------------------------------------------
# Trigger 2: recurring errors
# ---------------------------------------------------------------------------

# Where the path-token typically appears in a lesson_summary or context.
_PATH_RE = re.compile(r"([a-zA-Z0-9_\-/]+\.py)")


def get_recurring_errors(
    *, min_count: int = DEFAULT_ERROR_MIN_COUNT, days: int = DEFAULT_ERROR_WINDOW_DAYS
) -> list[dict[str, Any]]:
    """Return distinct error fingerprints with count + best-guess source file."""
    factory = _factory_or_none()
    if factory is None:
        return []
    since = _now() - timedelta(days=max(1, int(days)))
    with factory() as session:
        rows = list(
            session.execute(
                select(LearningLog)
                .where(
                    LearningLog.created_at >= since,
                    LearningLog.success.is_(False),
                )
                .order_by(LearningLog.created_at.desc())
                .limit(5_000)
            )
            .scalars()
            .all()
        )
    counter: Counter[str] = Counter()
    sample_paths: dict[str, str] = {}
    sample_messages: dict[str, str] = {}
    for r in rows:
        msg = (r.lesson_summary or "").strip()
        if not msg:
            continue
        # Fingerprint: first 80 chars, lowercased, whitespace-collapsed
        fp = re.sub(r"\s+", " ", msg.lower())[:80]
        counter[fp] += 1
        if fp not in sample_messages:
            sample_messages[fp] = msg[:300]
        if fp not in sample_paths:
            ctx = r.context if isinstance(r.context, dict) else {}
            path_hint = (
                str(ctx.get("file") or ctx.get("source") or ctx.get("module") or "")
                or _first_py_path(msg)
                or _first_py_path(str(r.outcome_json or {}))
                or ""
            )
            if path_hint:
                sample_paths[fp] = path_hint[:255]
    out: list[dict[str, Any]] = []
    for fp, count in counter.most_common(20):
        if int(count) < int(min_count):
            continue
        out.append(
            {
                "fingerprint": fp,
                "count": int(count),
                "message": sample_messages.get(fp, ""),
                "file": sample_paths.get(fp, ""),
            }
        )
    return out


def _first_py_path(text: str) -> str:
    m = _PATH_RE.search(text or "")
    if not m:
        return ""
    p = m.group(1)
    if p.startswith("core/") or p.startswith("services/") or p.startswith("api/"):
        return p
    return ""


# ---------------------------------------------------------------------------
# Trigger 3: metric decline (revenue / profit)
# ---------------------------------------------------------------------------


def get_declining_metrics(*, days: int = DEFAULT_METRIC_DECLINE_DAYS) -> list[dict[str, Any]]:
    """Detect metrics that declined ``days`` consecutive days.

    Today this only inspects ``OpportunityProfitLog`` (daily realized P&L per org).
    Extend with more metrics over time (inventory turnover, conversion rate, ...).
    """
    factory = _factory_or_none()
    if factory is None:
        return []
    days = max(2, int(days))
    since = _now() - timedelta(days=days + 1)
    with factory() as session:
        rows = list(
            session.execute(
                select(OpportunityProfitLog)
                .where(OpportunityProfitLog.created_at >= since)
                .order_by(OpportunityProfitLog.created_at.asc(), OpportunityProfitLog.id.asc())
                .limit(20_000)
            )
            .scalars()
            .all()
        )

    # Bucket profit_loss_amount by date.
    by_day: dict[str, float] = defaultdict(float)
    for row in rows:
        if not row.created_at:
            continue
        key = row.created_at.astimezone(timezone.utc).date().isoformat()
        try:
            by_day[key] += float(row.profit_loss_amount or 0)
        except (TypeError, ValueError):
            continue
    series = [by_day[k] for k in sorted(by_day.keys())][-days:]
    if len(series) < days:
        return []
    declining = all(series[i] > series[i + 1] for i in range(len(series) - 1))
    if not declining:
        return []
    return [
        {
            "metric": "daily_realized_pnl",
            "series": [round(v, 2) for v in series],
            "days": int(days),
            "delta": round(series[-1] - series[0], 2),
        }
    ]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def check_and_trigger(
    *,
    accuracy_threshold: float = DEFAULT_ACCURACY_THRESHOLD,
    accuracy_window_days: int = DEFAULT_ACCURACY_WINDOW_DAYS,
    error_min_count: int = DEFAULT_ERROR_MIN_COUNT,
    error_window_days: int = DEFAULT_ERROR_WINDOW_DAYS,
    metric_decline_days: int = DEFAULT_METRIC_DECLINE_DAYS,
) -> dict[str, Any]:
    """Run all checks. Returns a JSON-safe summary."""
    proposals: list[dict[str, Any]] = []

    low_acc = _check_low_accuracy(
        threshold=accuracy_threshold, window_days=accuracy_window_days
    )
    if low_acc is not None:
        res = propose_improvement(**low_acc)
        proposals.append({"check": "low_accuracy", **res})

    for err in get_recurring_errors(min_count=error_min_count, days=error_window_days):
        target = err.get("file") or "services/"  # generic if file unknown
        res = propose_improvement(
            trigger_type=_TRIGGER_RECURRING_ERROR,
            target=str(target)[:255],
            reason=f"Recurring error ({err['count']} occurrences in {error_window_days}d): {err['message'][:160]}",
            proposed_change=(
                "Inspect the path above and add defensive handling for the recurring failure: "
                "try/except with safe fallback, input validation, or upstream contract tightening."
            ),
            evidence={"recurring_error": err, "window_days": int(error_window_days)},
        )
        proposals.append({"check": "recurring_error", **res})

    for metric in get_declining_metrics(days=metric_decline_days):
        target = "services/predictive_engine.py"
        res = propose_improvement(
            trigger_type=_TRIGGER_METRIC_DECLINE,
            target=target,
            reason=f"{metric['metric']} declined {metric['days']} days (delta={metric['delta']}).",
            proposed_change=(
                "Open a research proposal for the affected business domain: re-examine signal "
                "thresholds, recheck feature drift, and propose a targeted experiment."
            ),
            evidence={"metric_decline": metric},
        )
        proposals.append({"check": "metric_decline", **res})

    return {
        "ok": True,
        "checked_at": _now().isoformat(),
        "proposals_count": sum(1 for p in proposals if p.get("ok")),
        "skipped_count": sum(1 for p in proposals if p.get("skipped")),
        "proposals": proposals,
    }


def recent_triggers(*, limit: int = 20, status: str | None = None) -> list[dict[str, Any]]:
    factory = _factory_or_none()
    if factory is None:
        return []
    with factory() as session:
        stmt = (
            select(EvolutionTrigger)
            .order_by(EvolutionTrigger.created_at.desc(), EvolutionTrigger.id.desc())
            .limit(max(1, min(int(limit), 200)))
        )
        if status:
            stmt = stmt.where(EvolutionTrigger.status == str(status))
        rows = list(session.execute(stmt).scalars().all())
    return [
        {
            "id": int(r.id),
            "trigger_type": r.trigger_type,
            "target": r.target,
            "reason": r.reason,
            "proposed_change": r.proposed_change,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
            "evidence": dict(r.evidence or {}),
        }
        for r in rows
    ]
