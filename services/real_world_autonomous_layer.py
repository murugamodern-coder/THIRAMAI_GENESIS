"""
Real-world autonomous execution layer: execution lifecycle, negotiation loop, autonomy confidence,
outcome truth (expected vs actual), and feedback into learning.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import NegotiationDeal, RealWorldExecution
from services.feedback_engine import calculate_prediction_accuracy, record_prediction_vs_actual
from services.lifecycle_state import lifecycle_from_real_world_state
from services.learning_engine import record_outcome, update_strategy_profiles
from services.negotiation_intelligence_engine import full_negotiation_pack
from services.predictive_engine import prediction_summary


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _public_id() -> str:
    return f"rwx_{uuid.uuid4().hex[:20]}"


# --- 1) Execution completion tracking ---

_VALID_STATES = {"initiated", "in_progress", "completed", "failed"}
_CRITICAL_ACTION_KEYWORDS = (
    "trade",
    "order",
    "payment",
    "transfer",
    "invoice",
    "contract",
    "deployment",
    "delete",
    "terminate",
)


def _is_critical_action_type(action_type: str) -> bool:
    t = str(action_type or "").strip().lower()
    if not t:
        return False
    return any(k in t for k in _CRITICAL_ACTION_KEYWORDS)


def create_real_world_execution(
    user_id: int,
    organization_id: int,
    *,
    action_type: str = "general",
    label: str = "",
    expected_outcome: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pid = _public_id()
    factory = get_session_factory()
    if not factory:
        return {"ok": False, "error": "Database unavailable"}
    with factory() as session:
        m0 = dict(meta or {})
        e0 = dict(m0.get("e2e") or {})
        e0.setdefault("stage", "initiated")
        e0["updated_at"] = _now().isoformat()
        m0["e2e"] = e0
        row = RealWorldExecution(
            public_id=pid,
            user_id=int(user_id),
            organization_id=int(organization_id),
            action_type=str(action_type or "general")[:64],
            label=str(label or "")[:500],
            state="initiated",
            expected_outcome_json=expected_outcome or {},
            meta_json=m0,
        )
        session.add(row)
        session.commit()
        eid = int(row.id)
    return {
        "ok": True,
        "public_id": pid,
        "id": eid,
        "state": "initiated",
        "lifecycle_state": lifecycle_from_real_world_state(state="initiated", e2e={"stage": "initiated"}),
    }


def set_execution_state(
    public_id: str,
    user_id: int,
    state: str,
    *,
    actual_outcome: dict[str, Any] | None = None,
    api_succeeded: bool | None = None,
) -> dict[str, Any]:
    st = str(state or "").strip()
    if st not in _VALID_STATES:
        return {"ok": False, "error": f"invalid state: use one of {sorted(_VALID_STATES)}"}
    factory = get_session_factory()
    if not factory:
        return {"ok": False, "error": "Database unavailable"}
    with factory() as session:
        row = session.execute(
            select(RealWorldExecution).where(
                RealWorldExecution.public_id == str(public_id)[:64],
                RealWorldExecution.user_id == int(user_id),
            )
        ).scalar_one_or_none()
        if not row:
            return {"ok": False, "error": "execution not found"}
        row.state = st
        row.updated_at = _now()
        m = dict(row.meta_json or {})
        e2e = dict(m.get("e2e") or {})
        if st == "in_progress":
            e2e["stage"] = "running"
            e2e["running_at"] = _now().isoformat()
        m["e2e"] = e2e
        row.meta_json = m
        if actual_outcome is not None:
            row.actual_outcome_json = {**(row.actual_outcome_json or {}), **actual_outcome}
        if api_succeeded is not None:
            row.api_succeeded = bool(api_succeeded)
        if st in ("completed", "failed"):
            row.resolved_at = _now()
        session.commit()
    return {
        "ok": True,
        "public_id": str(public_id),
        "state": st,
        "lifecycle_state": lifecycle_from_real_world_state(state=st, e2e=e2e),
    }


def verify_execution_outcome(
    public_id: str,
    user_id: int,
    organization_id: int,
    *,
    actual_outcome: dict[str, Any],
    api_succeeded: bool,
    note: str = "",
    require_external_closure: bool = False,
) -> dict[str, Any]:
    """Mark verification: compares expected vs actual heuristics; not only HTTP success.

    If *require_external_closure* is True and the API succeeded with a non-failed outcome, the row stays
    *in_progress* until :func:`confirm_real_world_closure` (E2E: running → verified → completed).
    Critical action types always force external closure confirmation.
    """
    act = actual_outcome or {}
    factory = get_session_factory()
    if not factory:
        return {"ok": False, "error": "Database unavailable"}
    e2e_snapshot: dict[str, Any] = {}
    with factory() as session:
        row = session.execute(
            select(RealWorldExecution).where(
                RealWorldExecution.public_id == str(public_id)[:64],
                RealWorldExecution.user_id == int(user_id),
            )
        ).scalar_one_or_none()
        if not row:
            return {"ok": False, "error": "execution not found"}
        critical = _is_critical_action_type(str(row.action_type or ""))
        required_external = bool(require_external_closure or critical)
        exp = row.expected_outcome_json or {}
        match_ok = _heuristic_outcome_match(exp, act)
        row.actual_outcome_json = act
        row.api_succeeded = bool(api_succeeded)
        row.outcome_verified = True
        row.outcome_assessment = "match" if match_ok is True else ("partial" if match_ok is None else "mismatch")
        row.verification_note = str(note or "")[:5000]
        row.updated_at = _now()
        m = dict(row.meta_json or {})
        e2e = dict(m.get("e2e") or {})
        e2e["reconciliation"] = {
            "at": _now().isoformat(),
            "expected_keys": list(exp.keys())[:20],
            "actual_keys": list(act.keys())[:20],
            "heuristic": "match" if match_ok is True else ("unclear" if match_ok is None else "mismatch"),
        }
        st_final: str
        if not api_succeeded:
            row.state = "failed"
            row.resolved_at = _now()
            e2e["stage"] = "failed"
            e2e["closure_pending"] = False
            st_final = "failed"
        elif match_ok is False:
            row.state = "failed"
            row.resolved_at = _now()
            e2e["stage"] = "failed"
            e2e["closure_pending"] = False
            st_final = "failed"
        elif required_external and api_succeeded and match_ok is not False:
            row.state = "in_progress"
            row.resolved_at = None
            e2e["stage"] = "verified"
            e2e["closure_pending"] = True
            e2e["verified_at"] = _now().isoformat()
            m["completion_signals"] = {
                **(m.get("completion_signals") or {}),
                "state_reconciled": True,
                "reconciled_at": _now().isoformat(),
            }
            st_final = "in_progress"
        else:
            row.state = "completed" if (match_ok is not False) else "failed"
            row.resolved_at = _now()
            e2e["stage"] = "completed" if row.state == "completed" else "failed"
            e2e["closure_pending"] = False
            e2e["completed_at"] = _now().isoformat()
            m["completion_signals"] = {
                **(m.get("completion_signals") or {}),
                "state_reconciled": True,
                "external_confirmed": True,
                "single_step": True,
                "at": _now().isoformat(),
            }
            st_final = str(row.state)
        e2e["updated_at"] = _now().isoformat()
        e2e["critical_action"] = bool(critical)
        m["e2e"] = e2e
        e2e_snapshot = dict(e2e)
        row.meta_json = m
        session.commit()
        eid, pid, ast = int(row.id), str(row.public_id), str(row.outcome_assessment or "")

    fb = record_outcome(
        user_id=int(user_id),
        organization_id=int(organization_id),
        source_type="real_world_execution",
        source_id=eid,
        input_data={
            "expected": exp,
            "public_id": pid,
            "outcome_assessment": ast,
            "require_external_closure": required_external,
            "critical_action": bool(critical),
        },
        outcome={
            **act,
            "outcome_assessment": ast,
            "api_succeeded": api_succeeded,
            "profit_loss": float(act.get("profit", act.get("realized", act.get("amount", 0))) or 0),
        },
    )
    predicted = {
        **(exp if isinstance(exp, dict) else {}),
        "strategy": "real_world_execution_verify",
        "source_type": "real_world_execution",
        "confidence": float((exp or {}).get("confidence") or 0.55),
    }
    feedback = record_prediction_vs_actual(
        f"rwe:{pid}:verify",
        predicted,
        act if isinstance(act, dict) else {},
        user_id=int(user_id),
        organization_id=int(organization_id),
    )
    trust = calculate_prediction_accuracy(int(user_id), limit=300)
    return {
        "ok": True,
        "public_id": pid,
        "outcome_assessment": ast,
        "state": st_final,
        "lifecycle_state": lifecycle_from_real_world_state(state=st_final, e2e=e2e_snapshot),
        "critical_action": bool(critical),
        "require_external_closure": bool(required_external),
        "e2e": e2e_snapshot,
        "learning": fb,
        "feedback": feedback,
        "trust": trust,
    }


def confirm_real_world_closure(
    public_id: str,
    user_id: int,
    organization_id: int,
    *,
    external_confirmed: bool = True,
    reconciled: bool = True,
    note: str = "",
) -> dict[str, Any]:
    """Complete E2E after *verify* with *require_external_closure* (real-world / external confirmation)."""
    factory = get_session_factory()
    if not factory:
        return {"ok": False, "error": "Database unavailable"}
    with factory() as session:
        row = session.execute(
            select(RealWorldExecution).where(
                RealWorldExecution.public_id == str(public_id)[:64],
                RealWorldExecution.user_id == int(user_id),
            )
        ).scalar_one_or_none()
        if not row:
            return {"ok": False, "error": "execution not found"}
        if not row.outcome_verified:
            return {"ok": False, "error": "outcome not verified yet; call verify first"}
        m = dict(row.meta_json or {})
        e2e = dict(m.get("e2e") or {})
        if str(row.state) == "completed":
            return {
                "ok": True,
                "skipped": "already completed",
                "public_id": str(row.public_id),
                "state": "completed",
                "lifecycle_state": lifecycle_from_real_world_state(state="completed", e2e=e2e),
            }
        if e2e.get("stage") != "verified" or not e2e.get("closure_pending"):
            return {
                "ok": False,
                "error": "not awaiting external closure: verify with require_external_closure first",
            }
        critical = _is_critical_action_type(str(row.action_type or ""))
        if critical and not bool(external_confirmed):
            return {
                "ok": False,
                "error": "critical_action_requires_external_confirmation",
                "public_id": str(row.public_id),
            }
        exp = row.expected_outcome_json or {}
        act = row.actual_outcome_json or {}
        row.state = "completed"
        row.resolved_at = _now()
        row.updated_at = _now()
        e2e["stage"] = "completed"
        e2e["closure_pending"] = False
        e2e["completed_at"] = _now().isoformat()
        m["e2e"] = e2e
        sig = dict(m.get("completion_signals") or {})
        sig["external_confirmed"] = bool(external_confirmed)
        sig["reconciled"] = bool(reconciled)
        sig["closed_at"] = _now().isoformat()
        m["completion_signals"] = sig
        if note:
            row.verification_note = (str(row.verification_note or "") + "\n" + str(note))[:5000]
        row.meta_json = m
        session.commit()
        eid = int(row.id)
        pid = str(row.public_id)
    fb = record_outcome(
        user_id=int(user_id),
        organization_id=int(organization_id),
        source_type="real_world_closure",
        source_id=eid,
        input_data={"public_id": pid, "external_confirmed": external_confirmed},
        outcome={"success": True, "note": "E2E closure confirmed", "profit_loss": 0.0},
    )
    predicted = {
        **(exp if isinstance(exp, dict) else {}),
        "strategy": "real_world_execution_closure",
        "source_type": "real_world_closure",
        "confidence": float((exp or {}).get("confidence") or 0.6),
    }
    feedback = record_prediction_vs_actual(
        f"rwe:{pid}:closure",
        predicted,
        act if isinstance(act, dict) else {},
        user_id=int(user_id),
        organization_id=int(organization_id),
    )
    trust = calculate_prediction_accuracy(int(user_id), limit=300)
    return {
        "ok": True,
        "public_id": pid,
        "state": "completed",
        "lifecycle_state": lifecycle_from_real_world_state(state="completed", e2e={"stage": "completed"}),
        "learning": fb,
        "feedback": feedback,
        "trust": trust,
    }


def reconcile_execution_state(
    public_id: str,
    user_id: int,
) -> dict[str, Any]:
    """Re-run expected vs actual reconciliation without mutating row state (signal for operators)."""
    factory = get_session_factory()
    if not factory:
        return {"ok": False, "error": "Database unavailable"}
    with factory() as session:
        row = session.execute(
            select(RealWorldExecution).where(
                RealWorldExecution.public_id == str(public_id)[:64],
                RealWorldExecution.user_id == int(user_id),
            )
        ).scalar_one_or_none()
        if not row:
            return {"ok": False, "error": "execution not found"}
        exp = row.expected_outcome_json or {}
        act = row.actual_outcome_json or {}
        match_ok = _heuristic_outcome_match(exp, act)
        m = dict(row.meta_json or {})
        m["reconciliation_scan"] = {
            "at": _now().isoformat(),
            "heuristic": "match" if match_ok is True else ("unclear" if match_ok is None else "mismatch"),
        }
        row.meta_json = m
        row.updated_at = _now()
        rpid = str(row.public_id)
        session.commit()
    return {
        "ok": True,
        "public_id": rpid,
        "heuristic": "match" if match_ok is True else ("unclear" if match_ok is None else "mismatch"),
    }


def _heuristic_outcome_match(expected: dict[str, Any], actual: dict[str, Any]) -> bool | None:
    if not expected or not actual:
        return None
    ek, ak = {k for k, v in expected.items() if v is not None}, {k for k, v in actual.items() if v is not None}
    if "success" in expected and "success" in actual:
        return bool(expected.get("success")) == bool(actual.get("success"))
    for k in ("revenue", "amount", "profit", "value"):
        if k in expected and k in actual:
            try:
                d = abs(float(expected[k]) - float(actual[k]))
                m = max(abs(float(expected[k])), 1.0)
                return d / m < 0.2
            except (TypeError, ValueError):
                return None
    if ek & ak:
        return len(ek & ak) > 0
    return None


def list_real_world_executions(
    user_id: int,
    *,
    state: str | None = None,
    limit: int = 40,
) -> dict[str, Any]:
    factory = get_session_factory()
    if not factory:
        return {"ok": False, "error": "Database unavailable", "items": []}
    with factory() as session:
        q = select(RealWorldExecution).where(RealWorldExecution.user_id == int(user_id))
        if state and state in _VALID_STATES:
            q = q.where(RealWorldExecution.state == state)
        rows = session.execute(
            q.order_by(RealWorldExecution.created_at.desc(), RealWorldExecution.id.desc()).limit(
                max(1, min(200, int(limit)))
            )
        ).scalars().all()
    items: list[dict[str, Any]] = []
    for r in rows:
        m = r.meta_json or {}
        e2e = m.get("e2e") if isinstance(m, dict) else {}
        items.append(
            {
                "id": int(r.id),
                "public_id": r.public_id,
                "action_type": r.action_type,
                "label": r.label,
                "state": r.state,
                "lifecycle_state": lifecycle_from_real_world_state(
                    state=str(r.state or ""),
                    e2e=(e2e if isinstance(e2e, dict) else {}),
                ),
                "e2e_stage": (e2e or {}).get("stage"),
                "closure_pending": bool((e2e or {}).get("closure_pending")),
                "api_succeeded": r.api_succeeded,
                "outcome_verified": r.outcome_verified,
                "outcome_assessment": r.outcome_assessment,
                "expected_keys": list((r.expected_outcome_json or {}).keys())[:20],
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return {"ok": True, "items": items}


# --- 2) Negotiation loop + memory ---

_DEAL_STATUS = {"open", "negotiating", "closed", "lost"}


def create_negotiation_deal(
    user_id: int,
    organization_id: int,
    title: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pid = f"ndl_{uuid.uuid4().hex[:18]}"
    factory = get_session_factory()
    if not factory:
        return {"ok": False, "error": "Database unavailable"}
    with factory() as session:
        row = NegotiationDeal(
            public_id=pid,
            user_id=int(user_id),
            organization_id=int(organization_id),
            title=str(title or "")[:500],
            status="open",
            context_json=context or {},
            messages_json=[],
        )
        session.add(row)
        session.commit()
    return {"ok": True, "public_id": pid, "status": "open"}


def _get_messages(msgs: Any) -> list[dict[str, Any]]:
    if isinstance(msgs, list):
        return [m for m in msgs if isinstance(m, dict)]
    if isinstance(msgs, dict) and "items" in msgs:
        return [m for m in (msgs.get("items") or []) if isinstance(m, dict)]
    return []


def _analyze_inbound(text: str) -> dict[str, Any]:
    t = (text or "").lower()
    nums = [float(n.replace(",", "")) for n in re.findall(r"[\d,]+(?:\.\d+)?", t) if n][:5]
    sentiment = "neutral"
    if re.search(r"\b(accept|agree|ok|proceed|confirm)\b", t):
        sentiment = "positive"
    elif re.search(r"\b(reject|cannot|unfortunately|no discount|pass)\b", t):
        sentiment = "negative"
    return {
        "sentiment": sentiment,
        "numeric_hints": nums[:3],
        "length": len(t),
    }


def append_negotiation_message(
    public_id: str,
    user_id: int,
    role: str,
    body: str,
) -> dict[str, Any]:
    role_norm = (role or "system").lower()[:24]
    factory = get_session_factory()
    if not factory:
        return {"ok": False, "error": "Database unavailable"}
    with factory() as session:
        row = session.execute(
            select(NegotiationDeal).where(
                NegotiationDeal.public_id == str(public_id)[:64], NegotiationDeal.user_id == int(user_id)
            )
        ).scalar_one_or_none()
        if not row:
            return {"ok": False, "error": "deal not found"}
        msgs = _get_messages(row.messages_json)
        entry = {
            "at": _now().isoformat(),
            "role": role_norm,
            "text": (body or "")[:12000],
        }
        if role_norm in ("counterparty", "inbound", "them"):
            entry["analysis"] = _analyze_inbound(entry["text"])
        msgs.append(entry)
        row.messages_json = msgs
        if row.status == "open" and len(msgs) > 0:
            row.status = "negotiating"
        row.updated_at = _now()
        if role_norm in ("counterparty", "inbound", "them"):
            row.last_analysis_json = entry.get("analysis") or {}
        session.commit()
    return {"ok": True, "public_id": str(public_id), "message_count": len(msgs)}


def negotiation_counter_suggestion(
    public_id: str,
    user_id: int,
    role: Literal["buyer", "seller"] = "buyer",
) -> dict[str, Any]:
    factory = get_session_factory()
    if not factory:
        return {"ok": False, "error": "Database unavailable"}
    with factory() as session:
        row = session.execute(
            select(NegotiationDeal).where(
                NegotiationDeal.public_id == str(public_id)[:64], NegotiationDeal.user_id == int(user_id)
            )
        ).scalar_one_or_none()
        if not row:
            return {"ok": False, "error": "deal not found"}
        ctx = row.context_json or {}
        pl = str(ctx.get("product_line") or row.title)[:2000]
    ref = float(ctx.get("reference_unit_price") or ctx.get("unit_price") or 0) or 100.0
    suppliers_list = ctx.get("suppliers")
    pack = full_negotiation_pack(
        product_line=pl,
        reference_unit_price=ref,
        currency=str(ctx.get("currency") or "INR"),
        market_volatility=str(ctx.get("volatility") or "medium")[:12],
        suppliers=suppliers_list if isinstance(suppliers_list, list) else None,
        role=role,
        your_company=str(ctx.get("your_company") or "our team")[:120],
    )
    tmpl = (pack or {}).get("templates") or {}
    return {
        "ok": bool((pack or {}).get("ok")),
        "public_id": str(public_id),
        "pack": pack,
        "suggested_opener": str(tmpl.get("email_opening") or "")[:4000],
        "suggested_counter": str(tmpl.get("email_counter") or "")[:4000],
    }


def run_negotiation_turn(
    public_id: str,
    user_id: int,
    counterparty_message: str,
) -> dict[str, Any]:
    a = append_negotiation_message(public_id, int(user_id), "counterparty", counterparty_message)
    if not a.get("ok"):
        return a
    c = negotiation_counter_suggestion(public_id, int(user_id), "buyer")
    return {**a, "counter_suggestion": c, "suggested_action": c.get("suggested_opener") or (c.get("templates") or {}).get("email_counter", "") if isinstance(c, dict) else None}


def set_deal_status(public_id: str, user_id: int, status: str) -> dict[str, Any]:
    s = str(status or "").lower()
    if s not in _DEAL_STATUS:
        return {"ok": False, "error": f"status must be one of {sorted(_DEAL_STATUS)}"}
    factory = get_session_factory()
    if not factory:
        return {"ok": False, "error": "Database unavailable"}
    with factory() as session:
        row = session.execute(
            select(NegotiationDeal).where(
                NegotiationDeal.public_id == str(public_id)[:64], NegotiationDeal.user_id == int(user_id)
            )
        ).scalar_one_or_none()
        if not row:
            return {"ok": False, "error": "deal not found"}
        row.status = s
        row.updated_at = _now()
        session.commit()
    return {"ok": True, "public_id": str(public_id), "status": s}


def get_negotiation_deal(public_id: str, user_id: int) -> dict[str, Any]:
    factory = get_session_factory()
    if not factory:
        return {"ok": False, "error": "Database unavailable"}
    with factory() as session:
        row = session.execute(
            select(NegotiationDeal).where(
                NegotiationDeal.public_id == str(public_id)[:64], NegotiationDeal.user_id == int(user_id)
            )
        ).scalar_one_or_none()
        if not row:
            return {"ok": False, "error": "deal not found"}
        r = row
    return {
        "ok": True,
        "public_id": r.public_id,
        "title": r.title,
        "status": r.status,
        "context_json": r.context_json or {},
        "messages": _get_messages(r.messages_json),
        "last_analysis": r.last_analysis_json or {},
    }


# --- 3) Autonomy confidence ---

def evaluate_autonomy_confidence(
    user_id: int,
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pred = prediction_summary(int(user_id))
    acc = calculate_prediction_accuracy(int(user_id), limit=150)
    trust = float(acc.get("system_trust_score") or 50.0) / 100.0
    confs = float(pred.get("confidence_score") or 0.5)
    risk = str(((pred.get("predicted_risk") or {}).get("risk_level")) or "medium")
    risk_p = 0.35 if risk == "low" else 0.65 if risk == "medium" else 0.9
    score = 0.38 * trust + 0.32 * min(0.99, max(0.1, confs)) + 0.3 * (1.0 - min(0.95, risk_p))
    ctx = context or {}
    if float(ctx.get("stake_in_inr") or 0) > 1_000_000:
        score -= 0.1
    if str(ctx.get("safety_critical") or "").lower() in ("1", "true", "yes"):
        score = min(score, 0.45)
    can_auto = bool(score >= 0.58)
    ask_user = not can_auto
    return {
        "ok": True,
        "autonomy_confidence_0_1": round(max(0.0, min(0.99, score)), 3),
        "can_act_without_approval": can_auto,
        "should_ask_user": ask_user,
        "factors": {
            "system_trust": round(trust, 3),
            "prediction_confidence": round(float(confs), 3),
            "risk_level": risk,
        },
    }


# --- 4) Outcome truth + 5) Feedback into learning ---

def record_outcome_truth(
    user_id: int,
    organization_id: int,
    execution_public_id: str,
    expected: dict[str, Any],
    actual: dict[str, Any],
    *,
    adjust_profiles: bool = True,
) -> dict[str, Any]:
    eid = str(execution_public_id)[:64]
    fb1 = record_prediction_vs_actual(
        f"rwe:{eid}",
        {**expected, "strategy": "outcome_truth", "confidence": float((expected or {}).get("confidence") or 0.55)},
        actual,
        user_id=int(user_id),
        organization_id=int(organization_id),
    )
    fb2 = record_outcome(
        user_id=int(user_id),
        organization_id=int(organization_id),
        source_type="outcome_truth",
        source_id=None,
        input_data={"execution_public_id": eid, "expected": expected},
        outcome={**actual, "profit_loss": float(actual.get("profit", actual.get("revenue") or 0) or 0), "note": "Outcome truth reconciliation"},
    )
    prof: dict[str, Any] | None = None
    if adjust_profiles:
        prof = update_strategy_profiles(int(user_id))
    return {
        "ok": True,
        "feedback": fb1,
        "learning": fb2,
        "strategy_profiles": prof,
    }


def capture_real_world_feedback(
    user_id: int,
    organization_id: int,
    kind: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    k = (kind or "event").lower()[:48]
    p = payload or {}
    note = f"Real-world event: {k}"
    pnl = float(p.get("amount") or p.get("revenue") or p.get("profit") or p.get("loss") or 0.0)
    if k in ("deal_closed_won", "revenue_actual"):
        note = f"{note}; amount={p.get('amount', pnl)}"
    if k in ("deal_closed_lost", "failure", "churn"):
        pnl = -abs(pnl) if pnl == 0 else pnl
    r = record_outcome(
        user_id=int(user_id),
        organization_id=int(organization_id),
        source_type="real_world_feedback",
        source_id=None,
        input_data={"kind": k, "payload": p},
        outcome={
            "note": note,
            "success": p.get("success", k in ("deal_closed_won", "revenue_actual")),
            "profit_loss": pnl,
        },
    )
    up = None
    if p.get("also_refresh_profiles"):
        up = update_strategy_profiles(int(user_id))
    return {"ok": True, "recorded": r, "strategy_profiles": up}
