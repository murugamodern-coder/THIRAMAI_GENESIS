from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import AutonomySetting


@dataclass(frozen=True)
class AutonomyPolicy:
    auto_mode_enabled: bool
    confidence_high_threshold: float
    confidence_medium_threshold: float
    auto_approve: dict[str, Any]


DEFAULT_POLICY: dict[str, Any] = {
    "thresholds": {"high": 0.92, "medium": 0.80},
    "autoApprove": {
        # Example policy shape:
        # "reorder_stock": {"maxQuantity": 50}
    },
}


def load_autonomy_policy(*, organization_id: int) -> AutonomyPolicy:
    oid = int(organization_id)
    factory = get_session_factory()
    if factory is None:
        return AutonomyPolicy(False, 0.92, 0.80, {})
    with factory() as session:
        row = session.scalar(select(AutonomySetting).where(AutonomySetting.organization_id == oid).limit(1))
        enabled = bool(getattr(row, "auto_mode_enabled", False)) if row is not None else False
        raw = dict(getattr(row, "policy", None) or DEFAULT_POLICY)

    thr = raw.get("thresholds") or {}
    try:
        high = float(thr.get("high", DEFAULT_POLICY["thresholds"]["high"]))
    except Exception:
        high = DEFAULT_POLICY["thresholds"]["high"]
    try:
        med = float(thr.get("medium", DEFAULT_POLICY["thresholds"]["medium"]))
    except Exception:
        med = DEFAULT_POLICY["thresholds"]["medium"]

    auto_approve = raw.get("autoApprove") or {}
    if not isinstance(auto_approve, dict):
        auto_approve = {}
    return AutonomyPolicy(
        auto_mode_enabled=enabled,
        confidence_high_threshold=max(0.0, min(1.0, high)),
        confidence_medium_threshold=max(0.0, min(1.0, med)),
        auto_approve=auto_approve,
    )


def policy_allows_auto_approve(*, policy: AutonomyPolicy, action: str, payload: dict[str, Any]) -> tuple[bool, str | None]:
    rules = policy.auto_approve.get(action) if isinstance(policy.auto_approve, dict) else None
    if not isinstance(rules, dict):
        return False, "policy_no_rule"
    if "maxQuantity" in rules:
        try:
            max_q = float(rules["maxQuantity"])
            q = float(payload.get("quantity") or payload.get("qty") or 0)
            if q <= 0:
                return False, "invalid_quantity"
            if q > max_q:
                return False, "quantity_over_limit"
        except Exception:
            return False, "policy_invalid_rule"
    return True, None

