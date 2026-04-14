"""Multi-source deep research: web, news RSS, govt, marketplaces, social, YouTube, academic (Tavily-backed where needed)."""

from __future__ import annotations

import hashlib
import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from services.research_common import groq_json_object_sync, tavily_search_sync
from services.research_schemes_service import find_schemes_sync

_log = logging.getLogger("thiramai.deep_research")

GOVT_HOST_HINTS = (
    "tn.gov.in",
    "mygov.in",
    "gov.in",
    "nic.in",
    "msme.gov.in",
    "nabard.org",
    "startupindia.gov.in",
    "udyamregistration.gov.in",
)
PRICE_PATTERN = re.compile(
    r"(₹|rs\.?|inr|rupees?)\s*[\d,]+(?:\.\d+)?|[\d,]+(?:\.\d+)?\s*(lakh|crore|lac)|price\s*[:=]\s*[\d,]+",
    re.I,
)


def _norm_url_key(url: str) -> str:
    u = (url or "").strip().lower()
    u = u.split("#", 1)[0].rstrip("/")
    if u.startswith("http://"):
        u = "https://" + u[7:]
    return u[:2000]


def _item_from_tavily_row(r: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        "source": source,
        "title": str(r.get("title") or "")[:500],
        "url": str(r.get("url") or "")[:2000],
        "snippet": str(r.get("content") or r.get("snippet") or "")[:8000],
    }


def _tavily_items(raw: dict[str, Any] | Any, *, source_label: str) -> list[dict[str, Any]]:
    if not isinstance(raw, dict) or raw.get("ok") is False:
        return []
    out: list[dict[str, Any]] = []
    for r in raw.get("results") or []:
        if isinstance(r, dict):
            out.append(_item_from_tavily_row(r, source_label))
    return out


def search_google_news_rss_sync(query: str, *, limit: int = 12) -> list[dict[str, Any]]:
    q = (query or "").strip()[:400]
    if not q:
        return []
    encoded = urllib.parse.quote_plus(q)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-IN&gl=IN&ceid=IN:en"
    items: list[dict[str, Any]] = []
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "ThiramaiJarvis/1.0 (research)"})
            resp.raise_for_status()
        root = ET.fromstring(resp.text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for channel in root.findall(".//channel"):
            for ent in channel.findall("item")[:limit]:
                title_el = ent.find("title")
                link_el = ent.find("link")
                desc_el = ent.find("description")
                title = (title_el.text or "").strip() if title_el is not None else ""
                link = (link_el.text or "").strip() if link_el is not None else ""
                desc = (desc_el.text or "").strip() if desc_el is not None else ""
                if not title and not link:
                    continue
                items.append(
                    {
                        "source": "news_rss",
                        "title": title[:500],
                        "url": link[:2000],
                        "snippet": desc[:4000],
                    }
                )
        for ent in root.findall(".//atom:entry", ns)[:limit]:
            title_el = ent.find("atom:title", ns)
            link_el = ent.find("atom:link", ns)
            summ_el = ent.find("atom:summary", ns)
            title = (title_el.text or "").strip() if title_el is not None else ""
            link = ""
            if link_el is not None:
                link = (link_el.get("href") or link_el.text or "").strip()
            summ = (summ_el.text or "").strip() if summ_el is not None else ""
            if title or link:
                items.append(
                    {"source": "news_rss", "title": title[:500], "url": link[:2000], "snippet": summ[:4000]}
                )
    except Exception as exc:
        _log.warning("google news rss failed: %s", exc)
    return items[:limit]


def search_all_sources(query: str, depth: str = "standard") -> dict[str, Any]:
    """Fetch from multiple channels. ``depth``: quick | standard | deep."""
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "query required", "items": []}
    d = (depth or "standard").strip().lower()
    if d not in ("quick", "standard", "deep"):
        d = "standard"

    items: list[dict[str, Any]] = []
    web = tavily_search_sync(q, max_results=10)
    if isinstance(web, dict) and web.get("ok") is False and d == "quick":
        return {"ok": False, "error": web.get("error") or "web search failed", "items": [], "depth": d}
    items.extend(_tavily_items(web, source_label="web"))

    if d == "quick":
        if not items and isinstance(web, dict) and web.get("ok") is False:
            return {"ok": False, "error": web.get("error") or "web search failed", "items": [], "depth": d}
        return {"ok": True, "depth": d, "items": items, "web_error": web.get("error") if isinstance(web, dict) else None}

    news = search_google_news_rss_sync(q, limit=10)
    items.extend(news)

    govt_q = f"{q} Tamil Nadu India MSME government scheme subsidy site:tn.gov.in OR site:mygov.in OR site:msme.gov.in"
    govt_raw = tavily_search_sync(govt_q[:400], max_results=8)
    items.extend(_tavily_items(govt_raw, source_label="govt_portal"))

    if d == "standard":
        return {"ok": True, "depth": d, "items": items}

    im = tavily_search_sync(f"{q} price supplier site:indiamart.com India"[:400], max_results=6)
    items.extend(_tavily_items(im, source_label="indiamart"))
    ti = tavily_search_sync(f"{q} quotation site:tradeindia.com"[:400], max_results=6)
    items.extend(_tavily_items(ti, source_label="tradeindia"))

    social = tavily_search_sync(f"{q} India business trend twitter X discussion 2026"[:400], max_results=5)
    items.extend(_tavily_items(social, source_label="social_trends"))

    yt = tavily_search_sync(f"{q} india industry review site:youtube.com"[:400], max_results=4)
    items.extend(_tavily_items(yt, source_label="youtube"))

    acad = tavily_search_sync(f"{q} site:arxiv.org OR site:researchgate.net"[:400], max_results=4)
    items.extend(_tavily_items(acad, source_label="academic"))

    return {"ok": True, "depth": d, "items": items}


def _classify_item(it: dict[str, Any]) -> list[str]:
    cats: list[str] = []
    url = (it.get("url") or "").lower()
    blob = f"{it.get('title') or ''} {it.get('snippet') or ''}".lower()
    if any(h in url for h in GOVT_HOST_HINTS) or "scheme" in blob and ("gov" in url or "subsidy" in blob):
        cats.append("govt_docs")
    if PRICE_PATTERN.search(blob):
        cats.append("prices")
    if "|" in (it.get("snippet") or "") or re.search(r"\b(mrp|per\s*kg|per\s*unit|ex[- ]?works)\b", blob):
        cats.append("structured")
    if not cats:
        cats.append("unstructured")
    return list(dict.fromkeys(cats))


def normalize_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate by URL/title hash and attach ``categories``."""
    seen_set: set[str] = set()
    out: list[dict[str, Any]] = []
    for it in results:
        if not isinstance(it, dict):
            continue
        key = _norm_url_key(str(it.get("url") or ""))
        if not key:
            key = "title:" + hashlib.sha1(f"{it.get('title')}|{it.get('snippet')[:80]}".encode()).hexdigest()[:16]
        if key in seen_set:
            continue
        seen_set.add(key)
        row = {**it, "categories": _classify_item(it)}
        out.append(row)
    return out


_STRUCTURE_EXTRACT_SYSTEM = """From business research snippets (URLs + text), output STRICT JSON:
{
  "tables": [ { "name": string, "headers": string[], "rows": string[][] } ],
  "price_list": [ { "item": string, "price_text": string, "source_url": string } ],
  "vendor_list": [ { "name": string, "url": string, "location": string, "rating": string } ],
  "govt_docs": [ { "title": string, "url": string, "summary": string } ],
  "statistics": [ { "label": string, "value": string } ]
}
Use only supported facts from the text; use empty arrays if unknown. Max 12 entries per array."""


def extract_structured_data(normalized: list[dict[str, Any]], query: str) -> dict[str, Any]:
    blob_parts = []
    for it in normalized[:25]:
        blob_parts.append(
            f"[{it.get('source')}] {it.get('title')}\n{it.get('url')}\n{(it.get('snippet') or '')[:1200]}\n---"
        )
    blob = "\n".join(blob_parts)[:20000]
    parsed = groq_json_object_sync(
        system=_STRUCTURE_EXTRACT_SYSTEM,
        user_content=f"Query: {query}\n\nSnippets:\n{blob}",
        max_tokens=3000,
    )
    empty = {"tables": [], "price_list": [], "vendor_list": [], "govt_docs": [], "statistics": []}
    if not isinstance(parsed, dict):
        return empty
    out = {**empty}
    for k in empty:
        v = parsed.get(k)
        if isinstance(v, list):
            out[k] = [x for x in v if isinstance(x, dict)][:20]
    return out


_ANALYSIS_SYSTEM = """You are a senior business analyst. From the user query, normalized source snippets, and structured extraction JSON, output STRICT JSON:
{
  "summary": string (2-4 sentences),
  "key_insights": string[] (3-7 bullets),
  "risks": string[] (2-5),
  "opportunities": string[] (2-6),
  "confidence_score": number between 0 and 1 (how actionable the synthesis is given source quality)
}
Be conservative: flag verification needs for prices and legal/subsidy claims."""


def analyze_research(
    query: str,
    results: list[dict[str, Any]],
    structured_data: dict[str, Any],
) -> dict[str, Any]:
    q = (query or "").strip()
    mini = []
    for it in results[:18]:
        mini.append(f"- [{it.get('source')}] {it.get('title')}: {(it.get('snippet') or '')[:400]}")
    user_blob = (
        f"Query: {q}\n\nNormalized highlights:\n" + "\n".join(mini) + f"\n\nStructured JSON:\n{structured_data!s}"[:22000]
    )
    parsed = groq_json_object_sync(system=_ANALYSIS_SYSTEM, user_content=user_blob, max_tokens=2000)
    default = {
        "summary": "",
        "key_insights": [],
        "risks": [],
        "opportunities": [],
        "confidence_score": 0.0,
    }
    if not isinstance(parsed, dict):
        return default
    try:
        conf = float(parsed.get("confidence_score", 0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    return {
        "summary": str(parsed.get("summary") or "")[:4000],
        "key_insights": [str(x) for x in (parsed.get("key_insights") or []) if x][:10],
        "risks": [str(x) for x in (parsed.get("risks") or []) if x][:8],
        "opportunities": [str(x) for x in (parsed.get("opportunities") or []) if x][:8],
        "confidence_score": conf,
    }


_COMPARISON_SYSTEM = """Build a vendor/product comparison for decision-makers. Output STRICT JSON:
{ "headers": string[], "rows": string[][] }
Use headers like Vendor, Price, Location, Rating, Notes when applicable. Max 8 rows; cells are short text."""


def query_implies_comparison(query: str) -> bool:
    ql = (query or "").lower()
    keys = (
        "compare",
        " vs ",
        "versus",
        "cheapest",
        "best price",
        "which supplier",
        "which vendor",
        "price comparison",
        "better deal",
    )
    return any(k in ql for k in keys)


def build_comparison_table(results: list[dict[str, Any]], *, query: str = "") -> dict[str, Any] | None:
    blob_parts = []
    for it in results[:22]:
        blob_parts.append(f"{it.get('title')}\n{it.get('url')}\n{(it.get('snippet') or '')[:900]}\n---")
    blob = "\n".join(blob_parts)[:18000]
    parsed = groq_json_object_sync(
        system=_COMPARISON_SYSTEM,
        user_content=f"User query: {query}\n\nSources:\n{blob}",
        max_tokens=1500,
    )
    if not isinstance(parsed, dict):
        return None
    headers = parsed.get("headers")
    rows = parsed.get("rows")
    if not isinstance(headers, list) or not isinstance(rows, list):
        return None
    headers = [str(h) for h in headers[:12]]
    clean_rows: list[list[str]] = []
    for r in rows[:12]:
        if isinstance(r, list):
            clean_rows.append([str(c)[:500] for c in r[: len(headers) or 8]])
    if not headers or not clean_rows:
        return None
    return {"headers": headers, "rows": clean_rows}


def find_cheapest_machine_sync(machine_name: str, *, user_id: int | None = None, organization_id: int | None = None) -> dict[str, Any]:
    m = (machine_name or "").strip()
    if not m:
        return {"ok": False, "error": "machine_name required"}
    bundle = search_all_sources(f"{m} machine equipment price India supplier", "deep")
    if not bundle.get("ok"):
        return {"ok": False, "error": "search failed", "items": bundle.get("items") or []}
    norm = normalize_results(bundle["items"])
    structured = extract_structured_data(norm, m)
    comp = build_comparison_table(norm, query=f"cheapest {m} price comparison IndiaMART TradeIndia")
    analysis = analyze_research(f"Lowest price and reliable suppliers for: {m}", norm, structured)
    out = {
        "ok": True,
        "machine": m,
        "structured_data": structured,
        "comparison_table": comp,
        "analysis": analysis,
        "sources": list({str(x.get("url") or "") for x in norm if x.get("url")})[:20],
    }
    uid = int(user_id) if user_id and int(user_id) > 0 else None
    oid = int(organization_id) if organization_id and int(organization_id) > 0 else None
    if uid and oid:
        try:
            from services.jarvis_proactive_service import upsert_market_opportunity_alert_sync

            if analysis.get("opportunities"):
                upsert_market_opportunity_alert_sync(
                    user_id=uid,
                    organization_id=oid,
                    message=f"Price scan: {m} — {analysis['opportunities'][0][:400]}",
                    payload={"kind": "cheapest_machine", "machine": m},
                )
        except Exception as exc:
            _log.debug("proactive cheapest_machine: %s", exc)
    return out


def find_govt_schemes_deep_sync(
    sector: str,
    state: str = "TN",
    business_type: str = "",
    *,
    user_id: int | None = None,
    organization_id: int | None = None,
) -> dict[str, Any]:
    sec = (sector or "").strip()
    st = (state or "TN").strip()
    bt = (business_type or "").strip()
    if not sec:
        return {"ok": False, "error": "sector required"}
    focus = f"{sec} {bt} NABARD refinance MSME credit guarantee TANSIM startup Tamil Nadu industrial policy".strip()
    base = find_schemes_sync(
        focus[:500],
        st,
        user_id=user_id,
        organization_id=organization_id,
        persist=True,
        match_alerts=True,
    )
    extra_q = f"{sec} {bt} government scheme subsidy India official portal"
    extra = tavily_search_sync(extra_q[:400], max_results=6)
    extra_items = normalize_results(_tavily_items(extra, source_label="govt_web"))
    structured = extract_structured_data(extra_items, focus)
    out = {**base, "structured_extras": structured, "depth": "govt_deep"}
    return out


def _maybe_proactive_hooks(
    *,
    user_id: int | None,
    organization_id: int | None,
    query: str,
    analysis: dict[str, Any],
    structured_data: dict[str, Any],
) -> None:
    uid = int(user_id) if user_id and int(user_id) > 0 else None
    oid = int(organization_id) if organization_id and int(organization_id) > 0 else None
    if not uid or not oid:
        return
    try:
        from services.jarvis_proactive_service import upsert_market_opportunity_alert_sync, upsert_research_scheme_alert_sync

        conf = float(analysis.get("confidence_score") or 0)
        opps = analysis.get("opportunities") or []
        if conf >= 0.55 and opps:
            upsert_market_opportunity_alert_sync(
                user_id=uid,
                organization_id=oid,
                message=f"Research insight: {query[:80]} — {opps[0][:500]}",
                payload={"kind": "deep_research", "query": query[:500]},
            )
        for doc in (structured_data.get("govt_docs") or [])[:2]:
            title = str(doc.get("title") or "Scheme signal")[:200]
            url = str(doc.get("url") or "")
            if title and url:
                upsert_research_scheme_alert_sync(
                    user_id=uid,
                    organization_id=oid,
                    message=f"Scheme / policy signal from research: {title}",
                    payload={"kind": "deep_research_govt", "url": url[:2000], "title": title},
                )
    except Exception as exc:
        _log.debug("proactive deep_research hooks: %s", exc)


def deep_research_sync(
    query: str,
    depth: str = "standard",
    *,
    user_id: int | None = None,
    organization_id: int | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "query required"}
    d = (depth or "standard").strip().lower()
    if d not in ("quick", "standard", "deep"):
        d = "standard"

    bundle = search_all_sources(q, d)
    if not bundle.get("ok"):
        return {"ok": False, "error": bundle.get("error") or "search failed", "items": bundle.get("items") or []}

    norm = normalize_results(bundle["items"])
    structured = extract_structured_data(norm, q)
    comp = None
    if query_implies_comparison(q):
        comp = build_comparison_table(norm, query=q)
    analysis = analyze_research(q, norm, structured)

    sources = []
    for it in norm:
        u = str(it.get("url") or "").strip()
        if u and u not in sources:
            sources.append(u)
    sources = sources[:25]

    project_id: int | None = None
    uid = int(user_id) if user_id and int(user_id) > 0 else None
    if persist and uid:
        try:
            from services.personal_command_center_service import create_research_project_sync

            links = {
                "kind": "deep_research",
                "query": q[:2000],
                "depth": d,
                "sources": sources,
                "structured_data": structured,
                "analysis": analysis,
                "comparison_table": comp,
                "categories_sample": [it.get("categories") for it in norm[:8]],
            }
            ok, _msg, rid = create_research_project_sync(
                user_id=uid,
                title=q[:200],
                description=(analysis.get("summary") or "")[:4000],
                links_json=links,
            )
            if ok and rid:
                project_id = int(rid)
        except Exception as exc:
            _log.warning("persist deep research project: %s", exc)

    _maybe_proactive_hooks(
        user_id=user_id,
        organization_id=organization_id,
        query=q,
        analysis=analysis,
        structured_data=structured,
    )

    return {
        "ok": True,
        "depth": d,
        "summary": analysis.get("summary"),
        "key_insights": analysis.get("key_insights"),
        "risks": analysis.get("risks"),
        "opportunities": analysis.get("opportunities"),
        "confidence_score": analysis.get("confidence_score"),
        "structured_data": structured,
        "comparison_table": comp,
        "sources": sources,
        "research_project_id": project_id,
        "items_preview": [{"title": it.get("title"), "source": it.get("source"), "url": it.get("url")} for it in norm[:12]],
    }
