"""
Full autonomous operator mode: continuous execution loop, deal intelligence evolution,
dynamic autonomy (assist / semi / full), per-domain reliability, self-correction.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import NegotiationDeal, RealWorldExecution, UserRuntimeConfig
from services.feedback_engine import calculate_prediction_accuracy
from services.learning_engine import analyze_patterns, record_outcome, update_strategy_profiles
from services.predictive_engine import prediction_summary
from services.real_world_autonomous_layer import get_negotiation_deal

_RUN_CFG_KEY = "autonomous_operator_v1"
_STALE_H = 48
_ESCALATE_RETRIES = 5
# Full autonomy only when both trust and mean domain reliability clear these (see autonomous_confidence_gate).
_DEFAULT_MIN_TRUST = 0.7
_DEFAULT_MIN_RELIABILITY = 0.6


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session_factory():
    try:
        return get_session_factory()
    except Exception:
        return None


def _runtime_get_json(user_id: int, key: str = _RUN_CFG_KEY) -> dict[str, Any]:
    f = _session_factory()
    if not f:
        return {}
    with f() as session:
        row = session.execute(
            select(UserRuntimeConfig)
            .where(
                UserRuntimeConfig.user_id == int(user_id),
                UserRuntimeConfig.config_key == str(key)[:128],
            )
            .limit(1)
        ).scalar_one_or_none()
        if row is None or not (row.config_value or "").strip():
            return {}
        try:
            return json.loads(row.config_value)
        except json.JSONDecodeError:
            return {}


def _runtime_set_json(user_id: int, data: dict[str, Any], key: str = _RUN_CFG_KEY) -> None:
    f = _session_factory()
    if not f:
        return
    blob = json.dumps(data, ensure_ascii=False)[:120_000]
    with f() as session:
        with session.begin():
            row = session.execute(
                select(UserRuntimeConfig)
                .where(
                    UserRuntimeConfig.user_id == int(user_id),
                    UserRuntimeConfig.config_key == str(key)[:128],
                )
                .limit(1)
            ).scalar_one_or_none()
            if row is None:
                row = UserRuntimeConfig(user_id=int(user_id), config_key=str(key)[:128], config_value=blob)
                session.add(row)
            else:
                row.config_value = blob
                row.updated_at = _now()


def _domain_for_execution(row: RealWorldExecution) -> str:
    m = row.meta_json or {}
    d = str(m.get("domain") or "").lower()
    if d in ("business", "trading", "research"):
        return d
    at = (row.action_type or "").lower()
    if any(x in at for x in ("trade", "stock", "position", "equity")):
        return "trading"
    if "research" in at:
        return "research"
    return "business"


def _get_messages(msgs: Any) -> list[dict[str, Any]]:
    if isinstance(msgs, list):
        return [m for m in msgs if isinstance(m, dict)]
    return []


# --- 1) Continuous execution loop + checkpoints ---

def add_execution_checkpoint(
    public_id: str,
    user_id: int,
    label: str,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    f = _session_factory()
    if not f:
        return {"ok": False, "error": "Database unavailable"}
    with f() as session:
        row = session.execute(
            select(RealWorldExecution).where(
                RealWorldExecution.public_id == str(public_id)[:64], RealWorldExecution.user_id == int(user_id)
            )
        ).scalar_one_or_none()
        if not row:
            return {"ok": False, "error": "execution not found"}
        m = dict(row.meta_json or {})
        cps = list(m.get("checkpoints") or [])
        cps.append(
            {
                "at": _now().isoformat(),
                "label": str(label or "checkpoint")[:200],
                "detail": detail or {},
            }
        )
        m["checkpoints"] = cps[-50:]
        m["last_checkpoint_at"] = _now().isoformat()
        row.meta_json = m
        row.updated_at = _now()
        session.commit()
    return {"ok": True, "public_id": str(public_id), "checkpoint_count": len(cps)}


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def run_continuous_execution_loop(
    user_id: int,
    organization_id: int,
    *,
    max_items: int = 30,
    stale_hours: int = _STALE_H,
) -> dict[str, Any]:
    """
    Scan open executions, append tick checkpoints, flag stale / unverified, suggest re-triggers.
    """
    f = _session_factory()
    if not f:
        return {"ok": False, "error": "Database unavailable"}
    lim = max(1, min(100, int(max_items)))
    stale_d = timedelta(hours=max(4, int(stale_hours)))
    now = _now()
    tick_actions: list[dict[str, Any]] = []
    with f() as session:
        rows = list(
            session.execute(
                select(RealWorldExecution)
                .where(RealWorldExecution.user_id == int(user_id), RealWorldExecution.state.in_(("initiated", "in_progress")))
                .order_by(RealWorldExecution.updated_at.asc(), RealWorldExecution.id.asc())
                .limit(lim)
            )
            .scalars()
            .all()
        )
        for r in rows:
            m = dict(r.meta_json or {})
            cps = list(m.get("checkpoints") or [])
            cps.append({"at": now.isoformat(), "label": "loop_tick", "detail": {"source": "continuous_loop"}})
            m["checkpoints"] = cps[-50:]
            m["last_loop_at"] = now.isoformat()
            ltc = int(m.get("loop_tick_count") or 0) + 1
            m["loop_tick_count"] = ltc
            retrigger: str | None = None
            e2e = dict(m.get("e2e") or {})
            e2e_stage = str(e2e.get("stage") or "")
            u = _aware(r.updated_at)
            if u is not None and (now - u) > stale_d:
                retrigger = "stale_no_progress_reattach_or_cancel"
            if e2e_stage == "verified" and e2e.get("closure_pending") and u is not None and (now - u) > stale_d:
                retrigger = retrigger or "await_external_confirmation_or_nudge"
            if not r.outcome_verified and r.state == "in_progress" and ltc >= 3:
                retrigger = retrigger or "reattach_verify_outcome"
            m["owner"] = "system"
            m["last_ownership_tick_at"] = now.isoformat()
            if retrigger:
                m["retrigger_suggested"] = retrigger
                m["retry_count"] = int(m.get("retry_count") or 0) + 1
            rc = int(m.get("retry_count") or 0)
            if rc >= int(_ESCALATE_RETRIES):
                m["escalation"] = "repeated_failure_hitl"
                m["safety"] = {**(m.get("safety") or {}), "hitl_recommended": True, "at": now.isoformat()}
            r.meta_json = m
            r.updated_at = now
            tick_actions.append(
                {
                    "public_id": r.public_id,
                    "state": r.state,
                    "suggestion": retrigger,
                    "domain": _domain_for_execution(r),
                }
            )
        session.commit()
    snap = {
        "last_loop_at": now.isoformat(),
        "items_touched": len(tick_actions),
    }
    cur = _runtime_get_json(int(user_id))
    cur["continuous_loop"] = snap
    _runtime_set_json(int(user_id), cur)
    return {
        "ok": True,
        "ticked": len(tick_actions),
        "actions": tick_actions,
        "organization_id": int(organization_id),
    }


# --- 2) Deal intelligence evolution ---

def evolve_deal_intelligence(user_id: int) -> dict[str, Any]:
    """
    Summarize closed/lost deals: simple winning vs losing text patterns; persist aggregate for future negotiation.
    """
    f = _session_factory()
    if not f:
        return {"ok": False, "error": "Database unavailable"}
    with f() as session:
        rows = list(
            session.execute(
                select(NegotiationDeal)
                .where(
                    NegotiationDeal.user_id == int(user_id),
                    NegotiationDeal.status.in_(("closed", "lost", "open", "negotiating")),
                )
                .order_by(NegotiationDeal.updated_at.desc(), NegotiationDeal.id.desc())
                .limit(80)
            )
            .scalars()
            .all()
        )
    wins: list[str] = []
    losses: list[str] = []
    for d in rows:
        msgs = _get_messages(d.messages_json)
        blob = " ".join(str(m.get("text") or "") for m in msgs).lower()
        if d.status == "closed":
            wins.append(blob[:2000])
        elif d.status == "lost":
            losses.append(blob[:2000])
    win_tokens = _top_tokens(" ".join(wins))
    lose_tokens = _top_tokens(" ".join(losses))
    pos_sig = ("agree", "confirm", "signed", "acceptable", "approved", "we can")
    neg_sig = ("cannot", "reject", "pass", "too high", "unfortunately", "not possible")
    winning_strategies = [f"Correlated terms in won threads: {', '.join(win_tokens[:5])}"] if win_tokens else ["insufficient_won_sample"]
    losing_patterns = [f"Correlated terms in lost threads: {', '.join(lose_tokens[:5])}"] if lose_tokens else ["insufficient_lost_sample"]
    if any(p in " ".join(wins) for p in pos_sig):
        winning_strategies.append("Explicit agreement language present in won deals")
    if any(p in " ".join(losses) for p in neg_sig):
        losing_patterns.append("Hard rejection or price-stall language in lost deals")
    out = {
        "ok": True,
        "sample": {"closed": len(wins), "lost": len(losses), "open_total": len(rows)},
        "winning_strategies": winning_strategies,
        "losing_patterns": losing_patterns,
        "feature_tokens_win": win_tokens[:12],
        "feature_tokens_lose": lose_tokens[:12],
        "updated_at": _now().isoformat(),
    }
    cur = _runtime_get_json(int(user_id))
    cur["deal_intelligence"] = out
    prev_play = list((cur.get("negotiation_playbook") or [])) if isinstance(cur.get("negotiation_playbook"), list) else []
    new_lines: list[dict[str, Any]] = []
    for line in (winning_strategies or [])[:5]:
        new_lines.append(
            {
                "text": str(line)[:2000],
                "kind": "leverage",
                "source": "evolve_deal_intelligence",
                "at": _now().isoformat(),
            }
        )
    for line in (losing_patterns or [])[:5]:
        new_lines.append(
            {
                "text": str(line)[:2000],
                "kind": "avoid",
                "source": "evolve_deal_intelligence",
                "at": _now().isoformat(),
            }
        )
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for ent in new_lines + prev_play:
        if not isinstance(ent, dict):
            continue
        t = str(ent.get("text") or "")[:500]
        if t and t in seen:
            continue
        if t:
            seen.add(t)
        merged.append(ent)
    cur["negotiation_playbook"] = merged[:28]
    _runtime_set_json(int(user_id), cur)
    with f() as session:
        with session.begin():
            for d in rows:
                if d.status not in ("closed", "lost"):
                    continue
                ctx = dict(d.context_json or {})
                ctx["deal_intelligence"] = {
                    "side": "won" if d.status == "closed" else "lost",
                    "tokens_hint": win_tokens[:6] if d.status == "closed" else lose_tokens[:6],
                }
                r2 = session.get(NegotiationDeal, int(d.id))
                if r2:
                    r2.context_json = ctx
                    r2.updated_at = _now()
    return out


# --- 3) Dynamic autonomy mode ---

def compute_dynamic_autonomy_mode(
    user_id: int,
    organization_id: int,
) -> dict[str, Any]:
    pred = prediction_summary(int(user_id))
    acc = calculate_prediction_accuracy(int(user_id), limit=200)
    ins = analyze_patterns(int(user_id), limit=100)
    trust = float(acc.get("system_trust_score") or 50.0) / 100.0
    wr = float(ins.get("win_rate") or 0.0)
    risk = str(((pred.get("predicted_risk") or {}).get("risk_level")) or "medium")
    risk_n = 0.35 if risk == "low" else 0.65 if risk == "medium" else 0.88
    # score 0..1: high => more autonomy
    score = 0.32 * trust + 0.38 * min(1.0, wr * 1.2) + 0.3 * (1.0 - min(0.95, risk_n))
    if str(acc.get("trend") or "") == "degrading":
        score -= 0.08
    if wr < 0.35:
        mode = "assist"
    elif score < 0.62 or risk == "high":
        mode = "semi_autonomous"
    else:
        mode = "full_autonomous"
    rel_blob = execution_reliability_by_domain(int(user_id), limit=200)
    doms = (rel_blob.get("domains") or {}) if rel_blob.get("ok") else {}
    rel_scores = [float((doms.get(d) or {}).get("reliability_score_0_1") or 0) for d in ("business", "trading", "research")]
    reliability_mean = sum(rel_scores) / max(len(rel_scores), 1)
    cur0 = _runtime_get_json(int(user_id))
    th = (cur0.get("operator_thresholds") or {}) if isinstance(cur0, dict) else {}
    min_trust = float(th.get("min_trust_0_1", _DEFAULT_MIN_TRUST))
    min_rel = float(th.get("min_reliability_0_1", _DEFAULT_MIN_RELIABILITY))
    effective = mode
    gate_reason: str | None = None
    if mode == "full_autonomous" and (trust < min_trust or reliability_mean < min_rel):
        effective = "semi_autonomous"
        gate_reason = "confidence_gate_trust_or_reliability"
    out = {
        "ok": True,
        "mode": mode,
        "effective_mode": effective,
        "score_0_1": round(max(0.0, min(0.99, score)), 3),
        "factors": {
            "trust_0_1": round(trust, 3),
            "win_rate_0_1": round(wr, 3),
            "risk_level": risk,
            "learning_trend": acc.get("trend"),
        },
        "autonomous_confidence_gate": {
            "reliability_mean_0_1": round(reliability_mean, 3),
            "min_trust_0_1": min_trust,
            "min_reliability_0_1": min_rel,
            "full_autonomy_allowed": effective == "full_autonomous",
            "downgraded": effective != mode and mode == "full_autonomous",
            "reason": gate_reason,
        },
    }
    cur = _runtime_get_json(int(user_id))
    out_store = {**out, "as_of": _now().isoformat(), "organization_id": int(organization_id)}
    cur["autonomy_mode"] = out_store
    _runtime_set_json(int(user_id), cur)
    return out


# --- 4) Execution reliability by domain ---

def execution_reliability_by_domain(
    user_id: int,
    *,
    limit: int = 200,
) -> dict[str, Any]:
    f = _session_factory()
    if not f:
        return {"ok": False, "error": "Database unavailable", "domains": {}}
    with f() as session:
        rows = list(
            session.execute(
                select(RealWorldExecution)
                .where(RealWorldExecution.user_id == int(user_id))
                .order_by(RealWorldExecution.created_at.desc(), RealWorldExecution.id.desc())
                .limit(max(10, min(500, int(limit))))
            )
            .scalars()
            .all()
        )
    by_d: dict[str, dict[str, float | int | list[Any]]] = {}
    for r in rows:
        dom = _domain_for_execution(r)
        b = by_d.setdefault(
            dom,
            {
                "n": 0,
                "completed": 0,
                "failed": 0,
                "verified": 0,
                "match": 0,
                "partial": 0,
                "mismatch": 0,
                "retries": [],
            },
        )
        b["n"] = int(b["n"]) + 1
        if r.state == "completed":
            b["completed"] = int(b["completed"]) + 1
        if r.state == "failed":
            b["failed"] = int(b["failed"]) + 1
        if r.outcome_verified:
            b["verified"] = int(b["verified"]) + 1
        a = (r.outcome_assessment or "") or ""
        if a == "match":
            b["match"] = int(b["match"]) + 1
        elif a == "partial":
            b["partial"] = int(b["partial"]) + 1
        elif a == "mismatch":
            b["mismatch"] = int(b["mismatch"]) + 1
        rc = int((r.meta_json or {}).get("retry_count") or 0)
        b["retries"] = b["retries"] if isinstance(b["retries"], list) else []
        b["retries"].append(rc)
    out_dom: dict[str, Any] = {}
    for dom, b in by_d.items():
        n = max(int(b["n"]), 1)
        v = int(b["verified"])
        m = int(b["match"])
        comp = int(b["completed"])
        rlist = b["retries"] if isinstance(b["retries"], list) else []
        avg_ret = sum(rlist) / max(len(rlist), 1) if rlist else 0.0
        rel = 0.4 * (comp / n) + 0.35 * (m / max(v, 1) if v else 0) + 0.25 * (1.0 / (1.0 + avg_ret))
        out_dom[dom] = {
            "n": n,
            "success_rate": round(comp / n, 3),
            "verification_rate": round(v / n, 3),
            "match_of_verified": round(m / max(v, 1), 3) if v else 0.0,
            "avg_retries": round(avg_ret, 3),
            "reliability_score_0_1": round(max(0.0, min(0.99, rel)), 3),
        }
    for k in ("business", "trading", "research"):
        out_dom.setdefault(
            k,
            {
                "n": 0,
                "success_rate": 0.0,
                "verification_rate": 0.0,
                "match_of_verified": 0.0,
                "avg_retries": 0.0,
                "reliability_score_0_1": 0.5,
            },
        )
    return {"ok": True, "domains": out_dom, "sample_rows": len(rows)}


# --- 5) Self-correction ---

def self_correct_on_mismatch(
    user_id: int,
    organization_id: int,
    execution_public_id: str,
) -> dict[str, Any]:
    f = _session_factory()
    if not f:
        return {"ok": False, "error": "Database unavailable"}
    with f() as session:
        row = session.execute(
            select(RealWorldExecution).where(
                RealWorldExecution.public_id == str(execution_public_id)[:64], RealWorldExecution.user_id == int(user_id)
            )
        ).scalar_one_or_none()
        if not row:
            return {"ok": False, "error": "execution not found"}
        oa = (row.outcome_assessment or "").strip()
        if oa == "match":
            return {"ok": True, "skipped": "outcome already matches expected", "public_id": str(execution_public_id)}
        m = dict(row.meta_json or {})
        m["self_corrected_at"] = _now().isoformat()
        m["self_correction_streak"] = int(m.get("self_correction_streak") or 0) + 1
        row.meta_json = m
        row.updated_at = _now()
        session.commit()
    up = update_strategy_profiles(int(user_id))
    recs = (analyze_patterns(int(user_id), limit=120) or {}).get("recommendations") or []
    rec = record_outcome(
        user_id=int(user_id),
        organization_id=int(organization_id),
        source_type="operator_self_correction",
        source_id=None,
        input_data={"execution_public_id": str(execution_public_id), "trigger": "outcome_mismatch"},
        outcome={"success": False, "note": "Self-correction: strategy profiles adjusted; see recommendations for next path.", "profit_loss": 0.0},
    )
    return {
        "ok": True,
        "public_id": str(execution_public_id),
        "strategy_update": up,
        "learning": rec,
        "recommended_next": recs[:4],
        "suggested_repaths": _suggest_repaths(),
    }


def _suggest_repaths() -> list[str]:
    return [
        "Re-run simulation with updated parameters before acting.",
        "Split the action into smaller verifiable sub-steps with checkpoints.",
        "Escalate to HITL approval for this fingerprint until two consecutive matches.",
    ]


def _top_tokens(text: str) -> list[str]:
    t = re.sub(r"[^\w\s]", " ", (text or "").lower())
    words = [w for w in t.split() if len(w) > 3]
    c = Counter(words)
    return [a for a, _ in c.most_common(15)]


# --- Optional: get snapshot ---

def ensure_operator_threshold_defaults(user_id: int) -> dict[str, Any]:
    """Merge default confidence-gate thresholds into user runtime (autonomous_operator_v1)."""
    cur = _runtime_get_json(int(user_id))
    th = dict(cur.get("operator_thresholds") or {})
    th.setdefault("min_trust_0_1", _DEFAULT_MIN_TRUST)
    th.setdefault("min_reliability_0_1", _DEFAULT_MIN_RELIABILITY)
    cur["operator_thresholds"] = th
    _runtime_set_json(int(user_id), cur)
    return th


def note_predicted_risk_for_operator(user_id: int) -> dict[str, Any]:
    """Cache latest risk for oversight; flag high-risk for HITL-style review when appropriate."""
    pred = prediction_summary(int(user_id))
    risk = str(((pred.get("predicted_risk") or {}).get("risk_level")) or "medium")
    cur = _runtime_get_json(int(user_id))
    cur["last_predicted_risk"] = {"level": risk, "at": _now().isoformat()}
    if risk == "high":
        s = cur.get("safety") if isinstance(cur.get("safety"), dict) else {}
        cur["safety"] = {
            **s,
            "high_risk_operations_review": True,
            "at": _now().isoformat(),
        }
    _runtime_set_json(int(user_id), cur)
    return {"ok": True, "risk_level": risk, "raw": pred}


def get_operator_snapshot(user_id: int) -> dict[str, Any]:
    from services.autonomous_business_operator import get_business_operator_policy

    return {
        "ok": True,
        "config": _runtime_get_json(int(user_id)),
        "policy": get_business_operator_policy(),
    }


def preflight_negotiation_with_intelligence(
    public_id: str,
    user_id: int,
) -> dict[str, Any]:
    """Return stored deal intel + last evolved hints for a deal."""
    d = get_negotiation_deal(str(public_id), int(user_id))
    if not d.get("ok"):
        return d
    rt = _runtime_get_json(int(user_id)) or {}
    agg = rt.get("deal_intelligence") or {}
    playbook = rt.get("negotiation_playbook") or []
    return {**d, "aggregate_deal_intelligence": agg, "negotiation_playbook": playbook}


def run_strategy_evolution_loop(user_id: int, organization_id: int) -> dict[str, Any]:
    """Generate strategies, simulate, experiment, promote, refresh profiles, retire low performers in runtime."""
    from services.strategy_generator_engine import (
        generate_strategies,
        promote_best_strategy,
        test_strategies,
    )

    gen = generate_strategies(int(user_id))
    items = gen.get("items") or []
    tested = test_strategies(int(user_id), int(organization_id), items)
    titems: list[dict[str, Any]] = list((tested.get("items") or []))
    prom = promote_best_strategy(int(user_id), titems) if titems else {"ok": False, "error": "no tests"}
    prof = update_strategy_profiles(int(user_id))
    cur = _runtime_get_json(int(user_id))
    prev = cur.get("strategy_pool")
    by_id: dict[str, Any] = {}
    if isinstance(prev, list):
        for p in prev:
            if isinstance(p, dict) and p.get("strategy_id"):
                by_id[str(p["strategy_id"])] = p
    for item in titems:
        s = item.get("strategy") or {}
        sid = str(s.get("strategy_id") or "")[:80]
        if not sid:
            continue
        expg = (item.get("experiment") or {})
        winner = str(expg.get("winner") or "") == "candidate"
        se = item.get("strategy_experiment") or {}
        se_ok = bool((se or {}).get("ok"))
        status = "retired" if not se_ok else ("deployed" if winner else "candidate")
        by_id[sid] = {
            "strategy_id": sid,
            "status": status,
            "at": _now().isoformat(),
        }
    best = (prom.get("best_strategy") or {}) if isinstance(prom, dict) and prom.get("ok") else {}
    if isinstance(best, dict) and best.get("strategy_id"):
        bsid = str(best.get("strategy_id"))[:80]
        if bsid in by_id and bool(prom.get("promoted")):
            by_id[bsid]["status"] = "deployed"
    ap = analyze_patterns(int(user_id), limit=120)
    wsrc = [str((w or {}).get("source_type") or "") for w in (ap.get("worst_patterns") or []) if isinstance(w, dict)][:3]
    cur["strategy_pool"] = list(by_id.values())[-36:]
    cur["strategy_retire_suggestions"] = wsrc
    cur["strategy_evolution"] = {
        "ok": True,
        "at": _now().isoformat(),
        "promotion": prom,
        "insight": ap,
    }
    _runtime_set_json(int(user_id), cur)
    return {
        "ok": True,
        "generated": gen,
        "tested": tested,
        "profile_refresh": prof,
        "strategy_pool": cur["strategy_pool"],
        "retire_suggestions": cur.get("strategy_retire_suggestions") or [],
    }


def environment_awareness_scan(
    user_id: int,
    organization_id: int,
    *,
    max_items: int = 24,
) -> dict[str, Any]:
    """Tag open executions with environment baselines; flag shifts (market, delays, context)."""
    from services.world_model_engine import get_world_model

    f = _session_factory()
    if not f:
        return {"ok": False, "error": "Database unavailable"}
    wm = get_world_model(int(user_id))
    fp_src = {
        "regime": (wm.get("market_behavior") or {}).get("regime"),
        "organization_id": int(organization_id),
    }
    fp = json.dumps(fp_src, sort_keys=True)[:2000]
    now = _now()
    with f() as session:
        rows = list(
            session.execute(
                select(RealWorldExecution)
                .where(
                    RealWorldExecution.user_id == int(user_id),
                    RealWorldExecution.state.in_(("initiated", "in_progress")),
                )
                .order_by(RealWorldExecution.updated_at.asc(), RealWorldExecution.id.asc())
                .limit(max(1, min(50, int(max_items))))
            )
            .scalars()
            .all()
        )
    out_rows: list[dict[str, Any]] = []
    for r in rows:
        m = dict(r.meta_json or {})
        base = m.get("environment_baseline")
        if isinstance(base, dict) and (base.get("fingerprint") or "") != fp:
            m["environment_signal"] = "context_shift"
            m["adaptive_hint"] = "revalidate_expected_outcome_check_delays"
        m["environment_baseline"] = {
            "fingerprint": fp,
            "regime": fp_src.get("regime"),
            "captured_at": now.isoformat(),
        }
        m["environment_last"] = {**fp_src, "captured_at": now.isoformat()}
        with f() as session2:
            with session2.begin():
                row2 = session2.get(RealWorldExecution, int(r.id))
                if row2:
                    row2.meta_json = m
                    row2.updated_at = now
        out_rows.append({"public_id": r.public_id, "shift": m.get("environment_signal")})
    return {"ok": True, "touched": len(out_rows), "rows": out_rows, "regime": fp_src.get("regime")}


def run_operator_mega_tick(
    user_id: int,
    organization_id: int,
    *,
    max_items: int = 30,
    stale_hours: int = _STALE_H,
    with_strategy: bool = False,
    with_deal_evolve: bool = False,
) -> dict[str, Any]:
    """Chained: continuous ownership loop, environment scan, optional deal evolve + strategy evolution."""
    a = run_continuous_execution_loop(
        int(user_id), int(organization_id), max_items=int(max_items), stale_hours=int(stale_hours)
    )
    b = environment_awareness_scan(int(user_id), int(organization_id))
    c = evolve_deal_intelligence(int(user_id)) if with_deal_evolve else None
    d = run_strategy_evolution_loop(int(user_id), int(organization_id)) if with_strategy else None
    m = compute_dynamic_autonomy_mode(int(user_id), int(organization_id))
    return {
        "ok": True,
        "continuous": a,
        "environment": b,
        "deal_intelligence": c,
        "strategy_evolution": d,
        "autonomy_mode": m,
    }
