"""
Decision intelligence: three-option analysis (A aggressive / B balanced / C safe),
recommendation with reasoning, and learning feedback on chosen option vs result.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import DecisionIntelligenceSession
from services.feedback_engine import calculate_prediction_accuracy
from services.agent_identity_continuity_engine import mission_alignment_score
from services.learning_engine import record_outcome
from services.simulation_engine import simulate_action_paths

_NAME = {"A": "aggressive", "B": "balanced", "C": "conservative"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session():
    return get_session_factory()


def _extract_stake(s: str) -> float:
    t = re.sub(r"[^0-9.]", " ", s or "")
    parts = [p for p in t.split() if p and re.match(r"^\d", p)]
    for p in parts[:3]:
        try:
            v = float(p)
            if v > 0:
                return v
        except ValueError:
            continue
    return 0.0


def _map_sim_path_to_options(
    sim_paths: list[dict[str, Any]], *, decision_brief: str
) -> dict[str, dict[str, Any]]:
    by_path: dict[str, dict[str, Any]] = {
        str(p.get("path") or "").lower(): p for p in (sim_paths or [])
    }
    out: dict[str, dict[str, Any]] = {}
    for label, pkey in (("A", "aggressive"), ("B", "balanced"), ("C", "conservative")):
        raw = by_path.get(pkey) or {}
        est_profit = float(raw.get("estimated_profit") or 0.0)
        r_raw = float(raw.get("estimated_risk") or (0.75 if pkey == "aggressive" else 0.45 if pkey == "balanced" else 0.28))
        risk_100 = int(max(0, min(100, round(r_raw * 100.0))) )
        p_succ = float(raw.get("success_probability") or 0.5)
        conf_pct = int(max(0, min(100, round(p_succ * 100.0))) )
        effort = 8 if pkey == "aggressive" else (5 if pkey == "balanced" else 3)
        if pkey == "aggressive" and r_raw > 0.7:
            effort = min(10, effort + 1)
        expected = (
            f"Estimated value ~{est_profit:,.0f} with success odds ~{conf_pct}%; "
            f"{'higher' if pkey == 'aggressive' else 'moderate' if pkey == 'balanced' else 'capped'} downside per risk model."
        )
        out[label] = {
            "label": _NAME[label],  # type: ignore[index]
            "key": pkey,
            "expected_outcome": expected,
            "risk_score": risk_100,
            "confidence_percent": conf_pct,
            "required_effort": int(effort),
            "raw": raw,
        }
    return out


def _identity_block(context: dict[str, Any] | None) -> dict[str, Any]:
    ctx = context if isinstance(context, dict) else {}
    ai = ctx.get("agent_identity") if isinstance(ctx.get("agent_identity"), dict) else {}
    master = ai.get("master_identity") if isinstance(ai.get("master_identity"), dict) else {}
    return master if master else ai


def _tokenize(text: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9_]+", str(text or "").lower()) if len(x) >= 3}


def _identity_long_term_alignment(*, decision_brief: str, context: dict[str, Any] | None = None) -> float:
    ident = _identity_block(context)
    mission = str(ident.get("mission") or "")
    goals = [str(x) for x in list(ident.get("long_term_goals") or [])]
    corpus = " ".join([mission] + goals)
    a = _tokenize(decision_brief)
    b = _tokenize(corpus)
    if not a or not b:
        return 0.0
    inter = len(a.intersection(b))
    union = len(a.union(b))
    if union <= 0:
        return 0.0
    return round(max(0.0, min(1.0, inter / union)), 4)


def _recommend_letter(
    sim: dict[str, Any],
    options: dict[str, dict[str, Any]],
    *,
    user_id: int,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rec_path = (sim.get("recommended_path") or {}) if isinstance(sim, dict) else {}
    pnm = str(rec_path.get("path") or "balanced").lower()
    path_to_letter = {"aggressive": "A", "balanced": "B", "conservative": "C"}
    primary = path_to_letter.get(pnm, "B")
    ctx = context if isinstance(context, dict) else {}
    prof = ctx.get("agent_identity") if isinstance(ctx.get("agent_identity"), dict) else {}
    style = str(prof.get("style") or "balanced").lower()
    identity = _identity_block(ctx)
    mission_priority = _identity_long_term_alignment(
        decision_brief=f"{ctx.get('title') or ''} {ctx.get('decision_brief') or ''}",
        context=ctx,
    )
    mission_mode = str(identity.get("master_priority") or "").lower()
    try:
        trust = float(calculate_prediction_accuracy(int(user_id), limit=200).get("system_trust_score") or 50.0)
    except Exception:
        trust = 50.0
    if trust < 38.0 and primary == "A":
        alt_note = "System trust is low; consider option C (safe) or B unless you can absorb variance."
    elif trust > 72.0 and primary == "C":
        alt_note = "Strong trust history: option A or B may be appropriate if the upside matches your mandate."
    else:
        alt_note = ""
    score = rec_path.get("path_score")
    if style == "aggressive":
        primary = "A" if trust >= 45.0 else primary
    elif style == "conservative":
        primary = "C" if trust < 75.0 else primary
    # Mission-aware nudge: allow bolder option only when trust/risk are healthy.
    option = options.get(primary) or {}
    current_risk = float(option.get("risk_score") or 50.0)
    if mission_priority >= 0.62 and trust >= 55.0 and current_risk <= 60.0:
        if primary == "C":
            primary = "B"
    if mission_priority >= 0.78 and trust >= 68.0 and current_risk <= 55.0 and mission_mode in {"aggressive_execution", "balanced_execution", "aggressive"}:
        if primary in {"B", "C"}:
            primary = "A"
    rsn = [
        f"Path '{pnm}' has the best risk-adjusted path score in the current model ({score}).",
        f"Model confidence blends prediction engine + feedback trust (~{trust:.0f}/100).",
    ]
    if alt_note:
        rsn.append(alt_note)
    if style in {"aggressive", "conservative", "balanced"}:
        rsn.append(f"Agent style bias applied: {style}.")
    return {
        "primary_option": primary,
        "aligned_path": pnm,
        "path_score": score,
        "reasoning": " ".join(rsn),
        "trust_score": round(trust, 2),
        "long_term_alignment": mission_priority,
        "identity_influence": round(max(0.0, min(1.0, (0.65 * mission_priority) + (0.35 * min(1.0, trust / 100.0)))), 4),
    }


def build_decision_analysis(
    *,
    user_id: int,
    title: str,
    decision_brief: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Produces A/B/C options and a recommendation. Does not persist; use `create_and_save_decision` for a session.
    """
    ctx = context or {}
    base = _extract_stake(decision_brief) or _extract_stake(str(ctx.get("stake") or ""))
    if base <= 0.0:
        base = max(100.0, float(ctx.get("expected_profit_baseline") or 5000.0))
    sim = simulate_action_paths(
        int(user_id),
        {
            "expected_profit": float(base),
            "action_summary": (decision_brief or title or "")[:2000],
        },
    )
    paths = sim.get("paths") or []
    options = _map_sim_path_to_options(paths, decision_brief=decision_brief)
    ctx = {
        **ctx,
        "title": title,
        "decision_brief": decision_brief,
    }
    rec = _recommend_letter(sim, options, user_id=int(user_id), context=ctx)
    prof = ctx.get("agent_identity") if isinstance(ctx.get("agent_identity"), dict) else {}
    align = mission_alignment_score(f"{title}. {decision_brief}", prof) if prof else None
    return {
        "ok": True,
        "title": (title or "Untitled decision")[:300],
        "decision_brief": (decision_brief or "")[:20000],
        "context": ctx,
        "options": {k: {kk: v for kk, v in o.items() if kk != "raw"} for k, o in options.items()},
        "options_with_model": options,
        "recommendation": {
            **rec,
            "suggested_path": f"Start with option {rec['primary_option']}: {options[rec['primary_option']].get('label', '')}",
            "mission_alignment": align,
        },
        "simulation": {"paths": paths, "world": sim.get("world_context")},
    }


def create_and_save_decision(
    *,
    user_id: int,
    organization_id: int,
    title: str,
    decision_brief: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pack = build_decision_analysis(
        user_id=int(user_id),
        title=title,
        decision_brief=decision_brief,
        context=context,
    )
    opts = {k: {kk: vv for kk, vv in v.items() if kk != "raw"} for k, v in (pack.get("options_with_model") or {}).items()}
    rec = pack.get("recommendation") or {}
    rec_public = {k: v for k, v in rec.items() if k in ("primary_option", "path_score", "reasoning", "trust_score", "suggested_path")}
    factory = _session()
    if factory is None:
        return {
            **{k: v for k, v in pack.items() if k not in ("options_with_model",)},
            "ok": bool(pack.get("ok")),
            "persisted": False,
            "error": "database_unavailable",
        }
    with factory() as session:
        row = DecisionIntelligenceSession(
            user_id=int(user_id),
            organization_id=int(organization_id),
            title=str(title or "")[:300],
            decision_brief=str(decision_brief or "")[:20000],
            context_json=(context or {}),
            options_json=opts,
            recommendation_json=rec_public,
            status="draft",
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return {
            **{k: v for k, v in pack.items() if k not in ("options_with_model",)},
            "ok": True,
            "persisted": True,
            "session_id": int(row.id),
            "session": {
                "id": int(row.id),
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            },
        }


def get_decision_session(*, session_id: int, user_id: int) -> dict[str, Any] | None:
    factory = _session()
    if factory is None:
        return None
    with factory() as session:
        r = session.get(DecisionIntelligenceSession, int(session_id))
        if r is None or r.user_id != int(user_id):
            return None
        return {
            "id": int(r.id),
            "organization_id": int(r.organization_id),
            "title": str(r.title or ""),
            "decision_brief": str(r.decision_brief or ""),
            "context_json": r.context_json or {},
            "options_json": r.options_json or {},
            "recommendation_json": r.recommendation_json or {},
            "status": str(r.status or "draft"),
            "selected_option": r.selected_option,
            "result_json": r.result_json or {},
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }


def list_decision_sessions(*, user_id: int, limit: int = 30) -> list[dict[str, Any]]:
    factory = _session()
    if factory is None:
        return []
    lim = max(1, min(100, int(limit)))
    with factory() as session:
        rows = (
            session.execute(
                select(DecisionIntelligenceSession)
                .where(DecisionIntelligenceSession.user_id == int(user_id))
                .order_by(DecisionIntelligenceSession.created_at.desc())
                .limit(lim)
            )
            .scalars()
            .all()
        )
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": int(r.id),
                "title": str(r.title or "")[:200],
                "status": r.status,
                "selected_option": r.selected_option,
                "recommendation_json": r.recommendation_json or {},
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return out


def select_decision_option(
    *, session_id: int, user_id: int, option: str
) -> dict[str, Any] | None:
    letter = (option or "").strip().upper()[:1]
    if letter not in "ABC":
        return None
    factory = _session()
    if factory is None:
        return None
    with factory() as session:
        r = session.get(DecisionIntelligenceSession, int(session_id))
        if r is None or r.user_id != int(user_id):
            return None
        r.selected_option = letter
        r.status = "selected"
        r.updated_at = _now()
        session.commit()
    return get_decision_session(session_id=int(session_id), user_id=int(user_id))


def record_decision_outcome(
    *,
    session_id: int,
    user_id: int,
    organization_id: int,
    success: bool,
    notes: str = "",
    value_realized: float | None = None,
    selected_option: str | None = None,
) -> dict[str, Any] | None:
    """
    Closes the session, stores the result, and appends a LearningLog for recursive improvement.
    """
    letter = (selected_option or "").strip().upper()[:1] or None
    if letter and letter not in "ABC":
        letter = None
    factory = _session()
    if factory is None:
        return None
    with factory() as session:
        r = session.get(DecisionIntelligenceSession, int(session_id))
        if r is None or r.user_id != int(user_id) or r.organization_id != int(organization_id):
            return None
        if letter and not (r.selected_option or "").strip():
            r.selected_option = letter
        r.result_json = {
            "success": bool(success),
            "notes": (notes or "")[:4000],
            "value_realized": float(value_realized) if value_realized is not None else None,
            "recorded_at": _now().isoformat(),
        }
        r.status = "closed"
        r.updated_at = _now()
        session.commit()
    sess = get_decision_session(session_id=int(session_id), user_id=int(user_id))
    learn_in = {
        "decision_session_id": int(session_id),
        "title": (sess or {}).get("title"),
        "decision_brief": (sess or {}).get("decision_brief"),
        "context_json": (sess or {}).get("context_json"),
        "options_considered": (sess or {}).get("options_json"),
        "recommendation": (sess or {}).get("recommendation_json"),
        "chosen": (sess or {}).get("selected_option"),
    }
    vr = float(value_realized) if value_realized is not None else 0.0
    learn_out = {
        "success": bool(success),
        "value_realized": value_realized,
        "realized_profit": vr,
        "profit_loss": vr if success else -abs(vr) if value_realized is not None else 0.0,
        "outcome_summary": (notes or "")[:2000] or "Outcome recorded",
        "option_chosen": (sess or {}).get("selected_option") if isinstance(sess, dict) else None,
    }
    try:
        record_outcome(
            user_id=int(user_id),
            organization_id=int(organization_id),
            source_type="decision_intelligence",
            source_id=int(session_id),
            input_data=learn_in,
            outcome=learn_out,
        )
    except Exception:
        pass
    return {**(sess or {}), "ok": True, "learning_queued": True}
