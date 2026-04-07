"""
Human-in-the-loop feedback adjusts per-tool **strictness multipliers** (PostgreSQL).

Feedback sentiment: -1 (stricter), 0 (neutral note), +1 (looser). Weights are clamped and aggregated
into ``AiRuleWeight.weight`` (baseline 1.0). ``evaluate_tool_action`` uses this to tighten ALLOW → PROPOSE.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from core.database import get_session_factory
from core.db.models import AiHitlFeedback, AiRuleWeight

_log = logging.getLogger(__name__)

_MIN_W = Decimal("0.70")
_MAX_W = Decimal("1.50")
_STEP = Decimal("0.06")


def strictness_multiplier(organization_id: int, rule_key: str) -> float:
    """Effective multiplier ≥1.0 means stricter scrutiny in policy post-processing."""
    oid = int(organization_id)
    key = (rule_key or "").strip()[:128]
    if oid <= 0 or not key:
        return 1.0
    factory = get_session_factory()
    if factory is None:
        return 1.0
    try:
        with factory() as session:
            row = session.execute(
                select(AiRuleWeight).where(
                    AiRuleWeight.organization_id == oid,
                    AiRuleWeight.rule_key == key,
                )
            ).scalar_one_or_none()
            if row is None:
                return 1.0
            return float(row.weight)
    except (OperationalError, ProgrammingError) as exc:
        _log.debug("hitl_rule_weights: read skipped %s", type(exc).__name__)
        return 1.0


def record_feedback(
    *,
    organization_id: int,
    user_id: int,
    rule_key: str,
    sentiment: int,
    comment: str = "",
    session: Session | None = None,
) -> dict[str, Any]:
    """Persist HITL event and bump aggregated weight for ``rule_key`` (usually ``tool_id``)."""
    oid = int(organization_id)
    uid = int(user_id)
    key = (rule_key or "").strip()[:128]
    if oid <= 0 or uid <= 0 or not key:
        return {"ok": False, "error": "invalid organization_id, user_id, or rule_key"}
    if sentiment not in (-1, 0, 1):
        return {"ok": False, "error": "sentiment must be -1, 0, or 1"}

    def _work(sess: Session) -> dict[str, Any]:
        fb = AiHitlFeedback(
            organization_id=oid,
            user_id=uid,
            rule_key=key,
            sentiment=sentiment,
            comment=(comment or "")[:4000],
        )
        sess.add(fb)
        row = sess.execute(
            select(AiRuleWeight).where(
                AiRuleWeight.organization_id == oid,
                AiRuleWeight.rule_key == key,
            )
        ).scalar_one_or_none()
        base = Decimal("1.0")
        if row is None:
            row = AiRuleWeight(organization_id=oid, rule_key=key, weight=base)
            sess.add(row)
            sess.flush()
        delta = _STEP * sentiment
        new_w = max(_MIN_W, min(_MAX_W, Decimal(str(row.weight)) - delta))
        row.weight = new_w
        sess.flush()
        return {"ok": True, "rule_key": key, "new_weight": float(new_w)}

    if session is not None:
        return _work(session)

    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "database unavailable"}
    try:
        with factory() as sess:
            with sess.begin():
                return _work(sess)
    except (OperationalError, ProgrammingError) as exc:
        return {"ok": False, "error": str(exc)}
