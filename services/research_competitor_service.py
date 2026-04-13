"""Competitor scan: Tavily (web + local query style) + structured JSON."""

from __future__ import annotations

import logging
from typing import Any

from core.database import get_session_factory
from core.db.models import ResearchDocument
from services.research_common import groq_json_object_sync, snippets_blob_from_tavily, tavily_search_sync

_log = logging.getLogger("thiramai.research_competitor")

_COMP_SYSTEM = """From the snippets, output STRICT JSON:
{
  "competitors": [ { "name": string, "location": string, "pricing": string, "strengths": string, "weaknesses": string } ],
  "gaps": [ string ],
  "opportunities": [ string ]
}
Infer cautiously; use "Unknown" if not in text."""


def analyze_competitors_sync(
    business_type: str,
    location: str,
    *,
    user_id: int | None = None,
    organization_id: int | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    bt = (business_type or "").strip()
    loc = (location or "").strip() or "India"
    if not bt:
        return {"ok": False, "error": "business_type required"}
    q = f"{bt} competitors near {loc} pricing market share India MSME"
    q2 = f"Google maps {bt} {loc} top companies list"
    raw = tavily_search_sync(q, max_results=6)
    raw2 = tavily_search_sync(q2, max_results=5)
    blobs = [snippets_blob_from_tavily(raw), snippets_blob_from_tavily(raw2)]
    blob = "\n\n".join(blobs)[:16000]
    if isinstance(raw, dict) and raw.get("ok") is False and isinstance(raw2, dict) and raw2.get("ok") is False:
        return {"ok": False, "error": raw.get("error") or raw2.get("error") or "search failed"}
    structured = groq_json_object_sync(
        system=_COMP_SYSTEM,
        user_content=f"Business type: {bt}\nLocation focus: {loc}\n\nSources:\n{blob}",
        max_tokens=2000,
    )
    if not structured:
        structured = {"competitors": [], "gaps": [], "opportunities": []}
    urls: list[str] = []
    for pack in (raw, raw2):
        if isinstance(pack, dict):
            for r in (pack.get("results") or [])[:6]:
                if isinstance(r, dict) and r.get("url"):
                    urls.append(str(r["url"]))
    out: dict[str, Any] = {"ok": True, "business_type": bt, "location": loc, **structured, "sources": urls[:8]}
    uid = int(user_id) if user_id and int(user_id) > 0 else None
    oid = int(organization_id) if organization_id and int(organization_id) > 0 else None
    if persist and uid:
        fac = get_session_factory()
        if fac is not None:
            try:
                with fac() as session:
                    with session.begin():
                        row = ResearchDocument(
                            user_id=uid,
                            organization_id=oid,
                            type="competitors",
                            query=f"{bt}|{loc}"[:2000],
                            content_json=dict(structured) if isinstance(structured, dict) else {},
                        )
                        session.add(row)
                        session.flush()
                        out["document_id"] = int(row.id)
            except Exception as exc:
                _log.warning("persist competitor research: %s", exc)
    return out
