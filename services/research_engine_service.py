"""Production-ready supplier research engine for Thiramai.

Features:
- Web search (Tavily)
- Summarization
- Supplier / pricing / contact extraction
- Stable structured output
"""

from __future__ import annotations

import os
import re
from typing import Any

from core.agents.researcher import perform_research

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PHONE_RE = re.compile(r"(?:\+91[-\s]?)?[6-9]\d{9}\b")
_PRICE_RE = re.compile(r"(₹|rs\.?|inr)\s*[\d,]+(?:\.\d+)?", re.I)

_SUPPLIER_SYSTEM = """You are an India B2B sourcing analyst.
From search snippets, extract suppliers and commercial signals.
Return STRICT JSON:
{
  "summary": "short summary",
  "suppliers": [
    {
      "name": "supplier name",
      "location": "city/state if known",
      "estimated_pricing": "price range text if found",
      "contacts": ["phone/email/website"],
      "link": "best source url"
    }
  ],
  "pricing_notes": ["..."],
  "verification_notes": ["..."]
}
Rules:
- Use only evidence from snippets.
- Keep max 20 suppliers.
- If uncertain, use empty string / [].
"""


def _cache_ttl() -> int:
    try:
        return max(60, int((os.getenv("THIRAMAI_RESEARCH_CACHE_TTL_SEC") or "180").strip()))
    except ValueError:
        return 180


def _heuristic_extract(results: list[dict[str, Any]]) -> dict[str, Any]:
    suppliers: list[dict[str, Any]] = []
    pricing_notes: list[str] = []
    seen_names: set[str] = set()

    for row in results[:30]:
        title = str(row.get("title") or "").strip()
        snippet = str(row.get("content") or row.get("snippet") or "").strip()
        url = str(row.get("url") or "").strip()
        blob = f"{title} {snippet}"
        if not blob.strip():
            continue

        emails = list(dict.fromkeys(_EMAIL_RE.findall(blob)))[:2]
        phones = list(dict.fromkeys(_PHONE_RE.findall(blob)))[:2]
        prices = list(dict.fromkeys(_PRICE_RE.findall(blob)))

        # naive supplier name from title prefix
        name_guess = title.split("|")[0].split("-")[0].strip()[:160] or "Unknown Supplier"
        key = name_guess.lower()
        if key in seen_names:
            continue
        seen_names.add(key)

        if prices:
            pricing_notes.append(f"{name_guess}: {', '.join(prices[:2])}")

        suppliers.append(
            {
                "name": name_guess,
                "location": "",
                "estimated_pricing": ", ".join(prices[:2]) if prices else "",
                "contacts": [*phones, *emails][:3],
                "link": url,
            }
        )
        if len(suppliers) >= 15:
            break

    return {
        "summary": "Heuristic supplier extraction from available web snippets.",
        "suppliers": suppliers,
        "pricing_notes": pricing_notes[:20],
        "verification_notes": [
            "Verify GSTIN, MOQ, freight, and payment terms directly with suppliers.",
            "Treat listed pricing as indicative unless quoted in writing.",
        ],
    }


def _llm_extract(query: str, results: list[dict[str, Any]]) -> dict[str, Any] | None:
    parts: list[str] = []
    for i, r in enumerate(results[:25], start=1):
        title = str(r.get("title") or "")[:300]
        url = str(r.get("url") or "")[:1200]
        snippet = str(r.get("content") or r.get("snippet") or "")[:1200]
        parts.append(f"[{i}] {title}\nURL: {url}\n{snippet}\n---")
    blob = "\n".join(parts)

    parsed = groq_json_object_sync(
        system=_SUPPLIER_SYSTEM,
        user_content=f"Query: {query}\n\nSnippets:\n{blob}",
        max_tokens=2200,
    )
    if not isinstance(parsed, dict):
        return None

    suppliers = parsed.get("suppliers")
    if not isinstance(suppliers, list):
        suppliers = []
    clean_suppliers: list[dict[str, Any]] = []
    for s in suppliers[:20]:
        if not isinstance(s, dict):
            continue
        clean_suppliers.append(
            {
                "name": str(s.get("name") or "")[:200],
                "location": str(s.get("location") or "")[:200],
                "estimated_pricing": str(s.get("estimated_pricing") or "")[:300],
                "contacts": [str(c)[:200] for c in (s.get("contacts") or []) if str(c).strip()][:5],
                "link": str(s.get("link") or "")[:1500],
            }
        )

    return {
        "summary": str(parsed.get("summary") or "")[:2000],
        "suppliers": clean_suppliers,
        "pricing_notes": [str(x)[:500] for x in (parsed.get("pricing_notes") or []) if str(x).strip()][:20],
        "verification_notes": [str(x)[:500] for x in (parsed.get("verification_notes") or []) if str(x).strip()][:20],
    }


def run_supplier_research_sync(
    query: str,
    *,
    max_results: int = 12,
) -> dict[str, Any]:
    """Main API for supplier-focused research.

    Example:
    >>> run_supplier_research_sync("Find HDPE pipe coupler suppliers in Tamil Nadu")
    """
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "query required"}

    from services.cache_layer import get_or_set_cache

    ttl = _cache_ttl()
    cache_key = f"thiramai:research:suppliers:{q.lower()[:280]}:{int(max_results)}"

    def _compute() -> dict[str, Any]:
        raw = perform_research(q, max_results=max(5, min(int(max_results), 30)))
        # Convert DuckDuckGo results to expected format
        results = []
        for item in raw:
            if isinstance(item, dict):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "content": item.get("snippet", ""),
                    "snippet": item.get("snippet", "")
                })
        
        links = list(dict.fromkeys(str(r.get("url") or "").strip() for r in results if r.get("url")))[:25]

        llm = _llm_extract(q, results)
        base = llm or _heuristic_extract(results)

        return {
            "ok": True,
            "query": q,
            "summary": base.get("summary") or "",
            "suppliers": base.get("suppliers") or [],
            "estimated_pricing": base.get("pricing_notes") or [],
            "links": links,
            "verification_notes": base.get("verification_notes") or [],
            "status": "success",
        }

    return get_or_set_cache(cache_key, ttl, _compute)


def perform_duckduckgo_research(query: str, max_results: int = 10) -> list[dict[str, Any]]:
    """
    Perform web research using DuckDuckGo.
    
    Returns list of search results with title, url, snippet.
    """
    return perform_research(query, max_results)

