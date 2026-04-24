"""
Persistent agent identity + continuity loop for consistent long-horizon behavior.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from core.database import get_session_factory
from core.db.models import DomainDominionProfile

_DEFAULT_PROFILE = {
    "mission": "Create measurable long-term value through reliable autonomous execution.",
    "long_term_vision": "Build a compounding, resilient, high-trust autonomous operating system.",
    "core_domains": ["business", "automation"],
    "risk_appetite": "medium",
    "style": "balanced",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def _normalize_style(s: str) -> str:
    v = str(s or "balanced").strip().lower()
    if v in {"aggressive", "balanced", "conservative"}:
        return v
    return "balanced"


def _normalize_profile(raw: dict[str, Any] | None) -> dict[str, Any]:
    p = dict(_DEFAULT_PROFILE)
    if isinstance(raw, dict):
        p["mission"] = str(raw.get("mission") or p["mission"])[:1000]
        p["long_term_vision"] = str(raw.get("long_term_vision") or p["long_term_vision"])[:2000]
        cds = raw.get("core_domains")
        if isinstance(cds, list):
            p["core_domains"] = [str(x)[:64] for x in cds if str(x).strip()][:12] or p["core_domains"]
        p["risk_appetite"] = str(raw.get("risk_appetite") or p["risk_appetite"])[:64]
        p["style"] = _normalize_style(str(raw.get("style") or p["style"]))
    return p


def get_agent_profile(*, user_id: int, organization_id: int) -> dict[str, Any]:
    fn = _session_factory_or_none()
    if fn is None:
        return {**_DEFAULT_PROFILE, "persisted": False}
    with fn() as session:
        row = session.execute(
            select(DomainDominionProfile).where(
                DomainDominionProfile.user_id == int(user_id),
                DomainDominionProfile.organization_id == int(organization_id),
            )
        ).scalar_one_or_none()
        if row is None:
            try:
                row = DomainDominionProfile(
                    user_id=int(user_id),
                    organization_id=int(organization_id),
                    active_domain="business",
                    meta_json={"agent_identity": _DEFAULT_PROFILE},
                )
                session.add(row)
                session.commit()
                return {**_DEFAULT_PROFILE, "persisted": True}
            except IntegrityError:
                session.rollback()
                return {**_DEFAULT_PROFILE, "persisted": False}
        meta = dict(row.meta_json or {})
        prof = _normalize_profile(meta.get("agent_identity") if isinstance(meta.get("agent_identity"), dict) else None)
        if "agent_identity" not in meta:
            meta["agent_identity"] = prof
            row.meta_json = meta
            session.commit()
        return {**prof, "persisted": True}


def update_agent_profile(
    *,
    user_id: int,
    organization_id: int,
    patch: dict[str, Any],
) -> dict[str, Any]:
    fn = _session_factory_or_none()
    if fn is None:
        return {"ok": False, "error": "database_unavailable"}
    with fn() as session:
        try:
            row = session.execute(
                select(DomainDominionProfile).where(
                    DomainDominionProfile.user_id == int(user_id),
                    DomainDominionProfile.organization_id == int(organization_id),
                )
            ).scalar_one_or_none()
            if row is None:
                row = DomainDominionProfile(
                    user_id=int(user_id),
                    organization_id=int(organization_id),
                    active_domain="business",
                    meta_json={},
                )
                session.add(row)
                session.flush()
            meta = dict(row.meta_json or {})
            cur = _normalize_profile(meta.get("agent_identity") if isinstance(meta.get("agent_identity"), dict) else None)
            nxt = _normalize_profile({**cur, **dict(patch or {})})
            meta["agent_identity"] = nxt
            row.meta_json = meta
            row.updated_at = datetime.now(timezone.utc)
            session.commit()
            return {"ok": True, "agent_profile": nxt}
        except IntegrityError:
            session.rollback()
            return {"ok": False, "error": "profile_persistence_blocked"}


def mission_alignment_score(text: str, profile: dict[str, Any]) -> float:
    t = str(text or "").lower()
    keys = [str(profile.get("mission") or ""), str(profile.get("long_term_vision") or "")]
    keys.extend(str(x) for x in (profile.get("core_domains") or []))
    hits = 0
    for k in keys:
        tok = [x for x in k.lower().split() if len(x) >= 4][:10]
        if any(x in t for x in tok):
            hits += 1
    denom = max(1, len(keys))
    return round(max(0.0, min(1.0, hits / denom)), 3)


def style_modifiers(style: str) -> dict[str, float]:
    s = _normalize_style(style)
    if s == "aggressive":
        return {"risk_multiplier": 1.18, "speed_bias": 1.2, "depth_bias": 1.15}
    if s == "conservative":
        return {"risk_multiplier": 0.82, "speed_bias": 0.85, "depth_bias": 0.75}
    return {"risk_multiplier": 1.0, "speed_bias": 1.0, "depth_bias": 1.0}


def apply_style_to_plan(plan_steps: list[dict[str, Any]], *, style: str) -> list[dict[str, Any]]:
    s = _normalize_style(style)
    out: list[dict[str, Any]] = []
    for row in list(plan_steps or []):
        if not isinstance(row, dict):
            continue
        r = dict(row)
        sk = str(r.get("step_kind") or "")
        if not sk.startswith("internal_"):
            rl = str(r.get("risk_level") or "medium").lower()
            if s == "aggressive":
                if rl == "low":
                    r["risk_level"] = "medium"
            elif s == "conservative":
                if rl == "high":
                    r["risk_level"] = "medium"
                elif rl == "medium":
                    r["risk_level"] = "low"
        payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
        payload = {**payload, "agent_style": s}
        if s == "aggressive":
            payload["execution_pace"] = "fast"
        elif s == "conservative":
            payload["execution_pace"] = "safe"
        else:
            payload["execution_pace"] = "balanced"
        r["payload"] = payload
        out.append(r)
    return out


def record_identity_memory(
    *,
    user_id: int,
    organization_id: int,
    memory_type: str,
    item: dict[str, Any],
) -> None:
    fn = _session_factory_or_none()
    if fn is None:
        return
    with fn() as session:
        row = session.execute(
            select(DomainDominionProfile).where(
                DomainDominionProfile.user_id == int(user_id),
                DomainDominionProfile.organization_id == int(organization_id),
            )
        ).scalar_one_or_none()
        if row is None:
            return
        meta = dict(row.meta_json or {})
        mem = meta.get("agent_identity_memory") if isinstance(meta.get("agent_identity_memory"), dict) else {}
        key = str(memory_type or "decisions")
        arr = list(mem.get(key) or [])
        arr.append({**dict(item or {}), "at": _now_iso()})
        mem[key] = arr[-120:]
        meta["agent_identity_memory"] = mem
        row.meta_json = meta
        row.updated_at = datetime.now(timezone.utc)
        session.commit()


def run_continuity_review(*, user_id: int, organization_id: int) -> dict[str, Any]:
    fn = _session_factory_or_none()
    if fn is None:
        return {"ok": False, "error": "database_unavailable"}
    profile = get_agent_profile(user_id=int(user_id), organization_id=int(organization_id))
    with fn() as session:
        row = session.execute(
            select(DomainDominionProfile).where(
                DomainDominionProfile.user_id == int(user_id),
                DomainDominionProfile.organization_id == int(organization_id),
            )
        ).scalar_one_or_none()
        if row is None:
            return {"ok": False, "error": "profile_not_found"}
        meta = dict(row.meta_json or {})
        mem = meta.get("agent_identity_memory") if isinstance(meta.get("agent_identity_memory"), dict) else {}
        decisions = list(mem.get("decisions") or [])[-20:]
        outcomes = list(mem.get("outcomes") or [])[-20:]
        patterns = list(mem.get("patterns") or [])[-20:]
        align_scores = [float(x.get("mission_alignment") or 0.0) for x in decisions if isinstance(x, dict)]
        align_avg = sum(align_scores) / max(1, len(align_scores)) if align_scores else 0.0
        success_n = sum(1 for x in outcomes if isinstance(x, dict) and bool(x.get("success")))
        outcome_rate = success_n / max(1, len(outcomes)) if outcomes else 0.0
        direction = "steady"
        if align_avg < 0.35:
            direction = "re-align_to_mission"
        elif outcome_rate < 0.45:
            direction = "stabilize_execution"
        elif patterns and any("failure" in str(p).lower() for p in patterns):
            direction = "harden_failure_patterns"
        review = {
            "at": _now_iso(),
            "mission": profile.get("mission"),
            "long_term_vision": profile.get("long_term_vision"),
            "alignment_avg": round(align_avg, 3),
            "outcome_success_rate": round(outcome_rate, 3),
            "direction_adjustment": direction,
        }
        patt = list(mem.get("patterns") or [])
        patt.append(
            {
                "direction_adjustment": direction,
                "alignment_avg": round(align_avg, 3),
                "outcome_success_rate": round(outcome_rate, 3),
                "at": _now_iso(),
            }
        )
        mem["patterns"] = patt[-120:]
        meta["agent_identity_memory"] = mem
        hist = list(meta.get("agent_continuity_reviews") or [])
        hist.append(review)
        meta["agent_continuity_reviews"] = hist[-120:]
        row.meta_json = meta
        row.updated_at = datetime.now(timezone.utc)
        session.commit()
        return {"ok": True, "review": review}
