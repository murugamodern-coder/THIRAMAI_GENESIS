"""Market research: Tavily + structured JSON via Groq; optional persist to ``research_documents``."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import ResearchDocument
from services.research_common import groq_json_object_sync, snippets_blob_from_tavily, tavily_search_sync

_log = logging.getLogger("thiramai.research_market")

_MARKET_SYSTEM = """You are a business analyst for Indian SMEs. From the web snippets provided, produce STRICT JSON with keys:
- market_size (string, INR context / India where possible)
- growth_rate (string)
- top_players (array of strings, company or brand names)
- price_trends (string)
- demand_forecast (string)
- opportunities (array of strings, actionable)
Use empty string or [] if unknown. No markdown, JSON only."""


def research_market_sync(
    query: str,
    *,
    user_id: int,
    organization_id: int | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    q = (query or "").strip()
    uid = int(user_id)
    if not q:
        return {"ok": False, "error": "query required"}
    raw = tavily_search_sync(
        f"India market size growth competitors price trends demand {q}",
        max_results=8,
    )
    if isinstance(raw, dict) and raw.get("ok") is False:
        return {"ok": False, "error": raw.get("error") or "search failed"}
    blob = snippets_blob_from_tavily(raw)
    structured = groq_json_object_sync(
        system=_MARKET_SYSTEM,
        user_content=f"Product/industry focus: {q}\n\nSources:\n{blob}",
        max_tokens=1200,
    )
    if not structured:
        structured = {
            "market_size": "",
            "growth_rate": "",
            "top_players": [],
            "price_trends": blob[:1200],
            "demand_forecast": "",
            "opportunities": [],
        }
    urls: list[str] = []
    if isinstance(raw, dict):
        for r in (raw.get("results") or [])[:8]:
            if isinstance(r, dict) and r.get("url"):
                urls.append(str(r["url"]))
    out: dict[str, Any] = {
        "ok": True,
        "query": q,
        "structured": structured,
        "sources": urls,
    }
    if persist and uid > 0:
        fac = get_session_factory()
        if fac is not None:
            try:
                with fac() as session:
                    with session.begin():
                        row = ResearchDocument(
                            user_id=uid,
                            organization_id=int(organization_id) if organization_id and int(organization_id) > 0 else None,
                            type="market",
                            query=q[:2000],
                            content_json={"structured": structured, "sources": urls},
                        )
                        session.add(row)
                        session.flush()
                        out["document_id"] = int(row.id)
            except Exception as exc:
                _log.warning("persist research_document: %s", exc)
    return out
