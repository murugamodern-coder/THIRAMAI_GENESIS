"""
Domain-aware execution intelligence shared by planning, scoring, and retries.
"""

from __future__ import annotations

import re
from typing import Any

from services.domain_dominion_engine import get_or_create_profile

_DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "trading": ("trade", "stock", "order", "market", "position", "broker"),
    "retail": ("sku", "inventory", "store", "retail", "customer"),
    "manufacturing": ("factory", "production", "bom", "vendor", "plant"),
    "logistics": ("shipment", "delivery", "fleet", "route", "logistics"),
    "agriculture": ("crop", "farm", "harvest", "agri", "seed", "fertilizer"),
    "energy": ("energy", "power", "grid", "solar", "battery"),
    "services": ("client", "service", "consulting", "proposal"),
    "business": ("business", "sales", "invoice", "pricing"),
}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9_]+", str(text or "").lower()) if len(t) >= 3}


def detect_domain_from_command(
    command: str,
    *,
    fallback_domain: str = "business",
) -> str:
    toks = _tokens(command)
    if not toks:
        return str(fallback_domain or "business")
    best = str(fallback_domain or "business")
    best_score = 0
    for dom, kws in _DOMAIN_KEYWORDS.items():
        sc = sum(1 for k in kws if k in toks)
        if sc > best_score:
            best, best_score = dom, sc
    return best


def load_domain_execution_context(
    *,
    user_id: int,
    organization_id: int,
    command: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = get_or_create_profile(user_id=int(user_id), organization_id=int(organization_id))
    knowledge = profile.get("knowledge_json") if isinstance(profile.get("knowledge_json"), dict) else {}
    configured_domain = str(profile.get("active_domain") or "business")
    detected_domain = detect_domain_from_command(command, fallback_domain=configured_domain)
    ctx = context if isinstance(context, dict) else {}
    risk_models = list(knowledge.get("risk_models") or [])
    pricing_patterns = list(knowledge.get("pricing_patterns") or [])
    suppliers = list(knowledge.get("suppliers") or [])
    workflows = list(knowledge.get("workflows") or [])
    return {
        "domain": detected_domain,
        "configured_domain": configured_domain,
        "profile_id": int(profile.get("id") or 0),
        "profile_enabled": bool(profile.get("enabled", True)),
        "suppliers": suppliers[:30],
        "workflows": workflows[:30],
        "pricing_patterns": pricing_patterns[:30],
        "risk_models": risk_models[:30],
        "context": ctx,
    }


def apply_domain_retry_strategy(
    retry_steps: list[dict[str, Any]],
    *,
    domain_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    dc = domain_context if isinstance(domain_context, dict) else {}
    if not retry_steps:
        return retry_steps
    risk_models = list(dc.get("risk_models") or [])
    suppliers = list(dc.get("suppliers") or [])
    pricing_patterns = list(dc.get("pricing_patterns") or [])
    dom = str(dc.get("domain") or "business")
    conservative = any(str(x).lower().find("conservative") >= 0 for x in risk_models)
    out: list[dict[str, Any]] = []
    for raw in retry_steps:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        payload = dict(row.get("payload") or {})
        sk = str(row.get("step_kind") or "")
        if sk in {"plugin_api", "plugin_email"} and suppliers:
            payload.setdefault("supplier_candidates", suppliers[:5])
        if sk == "plugin_api" and pricing_patterns:
            payload.setdefault("pricing_patterns", pricing_patterns[:5])
        if conservative:
            row["risk_level"] = "low" if str(row.get("risk_level") or "") in {"high", "medium"} else str(row.get("risk_level") or "low")
            payload.setdefault("domain_risk_mode", "conservative")
        payload.setdefault("domain", dom)
        row["payload"] = payload
        out.append(row)
    return out
