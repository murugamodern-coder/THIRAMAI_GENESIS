"""
Empire Governance Mode — P&L vs market, compliance snapshot, weekly revenue opportunities,
and exception-only brain UX (paired with ``THIRAMAI_EXCEPTION_ONLY_UX``).

Env:
  ``THIRAMAI_EMPIRE_GOVERNANCE_MODE`` — master flag for governance features in schedulers/API.
  ``THIRAMAI_EXCEPTION_ONLY_UX`` — suppress low-signal chat narratives (orchestrator).
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from sqlalchemy import case, select

from core.brain_output import ActionIntentNone, BrainStructuredResponse
from core.database import get_session_factory
from core.db.models import ComplianceCase
from core.sovereign_journal import record_background_action, record_cot_step
from services.economics_service import get_business_margin
from services.world_scanner import recent_world_events

_LOG = __import__("logging").getLogger(__name__)


def _truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


def empire_governance_enabled() -> bool:
    return _truthy("THIRAMAI_EMPIRE_GOVERNANCE_MODE")


def exception_only_ux_enabled() -> bool:
    return _truthy("THIRAMAI_EXCEPTION_ONLY_UX")


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _pl_dir() -> Path:
    d = _root() / "var" / "sovereign" / "pl_governance"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _opp_dir() -> Path:
    d = _root() / "var" / "sovereign" / "opportunities"
    d.mkdir(parents=True, exist_ok=True)
    return d


def fetch_open_compliance_cases(*, organization_id: int, limit: int = 25) -> list[dict[str, Any]]:
    factory = get_session_factory()
    if factory is None:
        return []
    oid = int(organization_id)
    with factory() as session:
        stmt = (
            select(ComplianceCase)
            .where(
                ComplianceCase.organization_id == oid,
                ComplianceCase.status == "open",
            )
            .order_by(
                case((ComplianceCase.deadline.is_(None), 1), else_=0),
                ComplianceCase.deadline.asc(),
                ComplianceCase.created_at.desc(),
            )
            .limit(limit)
        )
        rows = session.execute(stmt).scalars().all()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "id": int(r.id),
                    "title": (r.title or "")[:500],
                    "category": r.category,
                    "priority": r.priority,
                    "deadline": r.deadline.isoformat() if r.deadline else None,
                    "external_ref": r.external_ref,
                }
            )
        return out


def build_pl_vs_market_analysis(organization_id: int) -> dict[str, Any]:
    """
    Roll up ``economics_service`` margin, open ``compliance_cases``, latest world-scan correlation;
    optional Groq synthesis for operator dashboard.
    """
    oid = int(organization_id)
    margin = get_business_margin(oid)
    compliance = fetch_open_compliance_cases(organization_id=oid)
    worlds = recent_world_events(oid, limit=3)
    market_blob = ""
    for w in worlds:
        c = w.get("correlation") if isinstance(w, dict) else None
        if isinstance(c, dict):
            market_blob += (c.get("summary") or "") + "\n"

    record_cot_step(
        agent="empire_governance",
        phase="pl_market_scan",
        detail=f"net_profit={margin.get('net_profit_inr')} cases={len(compliance)}",
        organization_id=oid,
    )

    synthesis: dict[str, Any] = {
        "headline": "",
        "risks": [],
        "outlook_vs_business": "",
    }
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if key and margin.get("ok"):
        from groq import Groq

        prompt = (
            "You are a CFO advisor. Compare INDIAN SMB month-to-date P&L to EXTERNAL MARKET SNIPPETS. "
            "Return JSON only: headline (string max 400), risks (array max 5 strings), "
            "outlook_vs_business (string max 900) — is net profit trajectory aligned with sector trends?\n\n"
            f"P&L: {json.dumps(margin, default=str)[:6000]}\n\n"
            f"OPEN_COMPLIANCE_CASES: {json.dumps(compliance, default=str)[:4000]}\n\n"
            f"MARKET_SNIPPETS:\n{market_blob[:4000]}"
        )
        try:
            client = Groq(api_key=key)
            chat = client.chat.completions.create(
                model=(os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile").strip(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=900,
            )
            raw = (chat.choices[0].message.content or "").strip()
            m = re.search(r"\{[\s\S]*\}", raw)
            if m:
                synthesis = json.loads(m.group(0))
        except Exception as exc:
            _LOG.warning("empire_governance: groq pl analysis failed: %s", exc)

    record: dict[str, Any] = {
        "ts": time.time(),
        "organization_id": oid,
        "margin": margin,
        "compliance_open": compliance,
        "synthesis": synthesis,
    }
    line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    try:
        with (_pl_dir() / f"org_{oid}.jsonl").open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError as exc:
        _LOG.warning("empire_governance: pl persist failed: %s", exc)

    record_background_action(
        category="empire_pl",
        summary=(synthesis.get("headline") or f"P&L governance net={margin.get('net_profit_inr')}")[:1900],
        organization_id=oid,
        meta={"compliance_open_count": len(compliance)},
    )
    return record


def latest_pl_governance(organization_id: int) -> dict[str, Any] | None:
    path = _pl_dir() / f"org_{int(organization_id)}.jsonl"
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def build_weekly_revenue_opportunity(organization_id: int) -> dict[str, Any]:
    """
    One new revenue stream or major cost/automation idea per week with implementation plan (Markdown).
    """
    oid = int(organization_id)
    margin = get_business_margin(oid)
    compliance = fetch_open_compliance_cases(organization_id=oid, limit=12)
    worlds = recent_world_events(oid, limit=5)
    market = "\n".join(
        str((w.get("correlation") or {}).get("summary") or "") for w in worlds if isinstance(w, dict)
    )[:3500]

    plan_md = ""
    meta: dict[str, Any] = {"mode": "deterministic"}
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if key:
        from groq import Groq

        prompt = (
            "Weekly Empire Opportunity: propose exactly ONE new revenue stream OR cost-cutting automation "
            "for this business. Output Markdown with sections: ## Idea ## Why now ## 30-day plan ## Metrics ## Risks.\n"
            "Be specific to the data below (SKUs, margin pressure, compliance load).\n\n"
            f"P&L_SUMMARY:\n{json.dumps(margin, default=str)[:5000]}\n\n"
            f"COMPLIANCE_OPEN:\n{json.dumps(compliance, default=str)[:3000]}\n\n"
            f"MARKET:\n{market}"
        )
        try:
            client = Groq(api_key=key)
            chat = client.chat.completions.create(
                model=(os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile").strip(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.35,
                max_tokens=3500,
            )
            plan_md = (chat.choices[0].message.content or "").strip()
            meta["mode"] = "groq"
        except Exception as exc:
            plan_md = f"_Generation failed: {type(exc).__name__}_\n"
            meta["error"] = str(exc)[:500]
    else:
        plan_md = (
            "## Idea\nEnable GROQ_API_KEY for AI-generated weekly opportunities.\n\n"
            "## 30-day plan\n1) Set keys 2) Re-run job\n"
        )

    row = {
        "ts": time.time(),
        "organization_id": oid,
        "markdown": plan_md,
        "meta": meta,
    }
    line = json.dumps(row, ensure_ascii=False, default=str) + "\n"
    try:
        with (_opp_dir() / f"org_{oid}.jsonl").open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError as exc:
        _LOG.warning("empire_governance: opportunity persist failed: %s", exc)

    record_background_action(
        category="empire_opportunity",
        summary=plan_md[:1900],
        organization_id=oid,
        meta={"weekly": True},
    )
    record_cot_step(
        agent="empire_governance",
        phase="weekly_opportunity",
        detail=plan_md[:500],
        organization_id=oid,
    )
    return row


def latest_weekly_opportunity(organization_id: int) -> dict[str, Any] | None:
    path = _opp_dir() / f"org_{int(organization_id)}.jsonl"
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


_STRATEGIC_SPEAK_PATTERN = re.compile(
    r"(?i)\b(decision|approve|approval|compliance|tax law|legal risk|strategic|material weakness|"
    r"urgent|lawsuit|penalty|violation|must\s+you|should\s+i\s+file|board|investor)\b"
)


def maybe_apply_exception_only_ux(
    structured: BrainStructuredResponse,
    *,
    route_tag: str,
    user_message: str,
    structured_parse_ok: bool,
) -> BrainStructuredResponse:
    """
    If Empire exception-only mode: hide low-signal ``none``-intent replies (single-space narrative + flag).
    Chat API maps this to empty strings for the client.
    """
    if not empire_governance_enabled() or not exception_only_ux_enabled():
        return structured
    if route_tag in ("routine_brief", "preflight_veto", "ErrorFallback"):
        return structured
    if not structured_parse_ok:
        return structured
    if not isinstance(structured.action_intent, ActionIntentNone):
        return structured
    narrative = (structured.narrative or "").strip()
    if len(narrative) > 1800:
        return structured
    if _STRATEGIC_SPEAK_PATTERN.search(structured.narrative or ""):
        return structured
    return structured.model_copy(update={"narrative": " ", "empire_ux": "nominal_silence"})
