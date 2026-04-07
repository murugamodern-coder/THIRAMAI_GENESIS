"""
Stage 5 — World Scanner: periodic external signal harvest (RSS + optional Playwright pages),
correlation with tenant business snapshot (``vault`` / ``business_current``), strategic proposals.

Schedule: every 4 hours via ``workers.sovereign_scheduler`` (``THIRAMAI_SOVEREIGN_SCHEDULER=1``).

Env:
  ``THIRAMAI_WORLD_RSS_FEEDS`` — comma-separated RSS URLs
  ``THIRAMAI_WORLD_PLAYWRIGHT_URLS`` — optional extra JS-heavy pages (requires ``playwright``)
  ``THIRAMAI_WORLD_SCAN_PLAYWRIGHT`` — set ``1`` to fetch playwright URLs
"""

from __future__ import annotations

import json
import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import httpx

from core.sovereign_journal import record_background_action, record_cot_step

_LOG = __import__("logging").getLogger(__name__)

DEFAULT_RSS = (
    "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en",
    "https://www.thehindubusinessline.com/economy/feeder/default.rss",
)


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _business_snapshot_excerpt(organization_id: int, max_chars: int = 6000) -> str:
    """Prefer tenant vault business file when present."""
    from vault_memory import BUSINESS_CURRENT_NAME, tenant_vault_root

    try:
        troot = tenant_vault_root(int(organization_id))
        p = troot / BUSINESS_CURRENT_NAME
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")[:max_chars]
    except Exception:
        pass
    legacy = _root() / "vault" / "business_current.txt"
    if legacy.is_file():
        return legacy.read_text(encoding="utf-8", errors="replace")[:max_chars]
    return ""


def _rss_feeds() -> list[str]:
    raw = (os.getenv("THIRAMAI_WORLD_RSS_FEEDS") or "").strip()
    if raw:
        return [u.strip() for u in raw.split(",") if u.strip().startswith("http")]
    return list(DEFAULT_RSS)


def _parse_rss_titles(xml_text: str, max_items: int = 25) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    try:
        root = ET.fromstring(xml_text[:2_000_000])
    except ET.ParseError:
        return out
    # RSS 2.0
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if title:
            out.append({"title": title, "link": link, "source": "rss"})
        if len(out) >= max_items:
            break
    if out:
        return out
    # Atom (tags often namespaced)
    for entry in root.iter():
        tag = entry.tag.split("}")[-1] if "}" in entry.tag else entry.tag
        if tag != "entry":
            continue
        title = ""
        link = ""
        for child in entry:
            ct = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if ct == "title" and child.text:
                title = child.text.strip()
            elif ct == "link" and child.get("href"):
                link = (child.get("href") or "").strip()
        if title:
            out.append({"title": title, "link": link, "source": "atom"})
        if len(out) >= max_items:
            break
    return out


def _fetch_rss_headlines() -> list[dict[str, str]]:
    headers = {"User-Agent": "THIRAMAI-WorldScanner/1.0"}
    merged: list[dict[str, str]] = []
    with httpx.Client(timeout=45.0, follow_redirects=True) as client:
        for url in _rss_feeds():
            try:
                r = client.get(url, headers=headers)
                r.raise_for_status()
                merged.extend(_parse_rss_titles(r.text))
            except Exception as exc:
                _LOG.warning("world_scanner: rss fetch failed %s: %s", url, exc)
    # de-dupe titles
    seen: set[str] = set()
    uniq: list[dict[str, str]] = []
    for row in merged:
        key = row["title"][:200].lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(row)
    return uniq[:40]


def _fetch_playwright_snippets() -> list[dict[str, str]]:
    if (os.getenv("THIRAMAI_WORLD_SCAN_PLAYWRIGHT") or "").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return []
    urls_raw = (os.getenv("THIRAMAI_WORLD_PLAYWRIGHT_URLS") or "").strip()
    if not urls_raw:
        return []
    urls = [u.strip() for u in urls_raw.split(",") if u.strip().startswith("http")]
    if not urls:
        return []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _LOG.warning("world_scanner: playwright not installed; skip JS URLs")
        return []
    out: list[dict[str, str]] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            for url in urls[:5]:
                try:
                    page.goto(url, timeout=60000, wait_until="domcontentloaded")
                    text = page.inner_text("body")[:12000]
                    snippet = re.sub(r"\s+", " ", text).strip()[:2500]
                    if snippet:
                        out.append({"title": f"page:{url[:80]}", "link": url, "body_excerpt": snippet})
                except Exception as exc:
                    _LOG.warning("world_scanner: playwright %s: %s", url, exc)
            browser.close()
    except Exception as exc:
        _LOG.warning("world_scanner: playwright session failed: %s", exc)
    return out


def _groq_correlate(*, business: str, headlines: list[dict[str, str]]) -> dict[str, Any]:
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not key or not headlines:
        return {
            "summary": "External headlines collected; configure GROQ_API_KEY for AI correlation.",
            "strategic_proposals": [],
            "risk_flags": [],
        }
    from groq import Groq

    hl = "\n".join(f"- {h.get('title', '')}" for h in headlines[:35])
    prompt = (
        "You are a strategic analyst. Given BUSINESS CONTEXT (tenant) and WORLD HEADLINES, "
        "output compact JSON only with keys: summary (string, max 800 chars), "
        "strategic_proposals (array of strings, max 5), risk_flags (array of strings, max 5), "
        "legal_or_tax_alerts (array of strings, max 3). "
        "Focus on market, regulatory, and tax changes relevant to this business.\n\n"
        f"BUSINESS CONTEXT:\n{business[:5000] or '[empty]'}\n\nHEADLINES:\n{hl}"
    )
    raw = ""
    try:
        client = Groq(api_key=key)
        chat = client.chat.completions.create(
            model=(os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile").strip(),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1200,
        )
        raw = (chat.choices[0].message.content or "").strip()
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            return json.loads(m.group(0))
    except Exception as exc:
        _LOG.warning("world_scanner: groq correlate failed: %s", exc)
    return {
        "summary": (raw[:1200] if raw else "Correlation unavailable."),
        "strategic_proposals": [],
        "risk_flags": [],
        "legal_or_tax_alerts": [],
    }


def _events_path(organization_id: int) -> Path:
    d = _root() / "var" / "sovereign" / "world_events"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"org_{int(organization_id)}.jsonl"


def append_world_scan_record(organization_id: int, record: dict[str, Any]) -> None:
    line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    try:
        path = _events_path(organization_id)
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError as exc:
        _LOG.warning("world_scanner: persist failed: %s", exc)


def run_world_scan_for_org(organization_id: int) -> dict[str, Any]:
    oid = int(organization_id)
    record_cot_step(
        agent="world_scanner",
        phase="start",
        detail=f"Harvesting external signals for org {oid}",
        organization_id=oid,
    )
    headlines = _fetch_rss_headlines()
    for extra in _fetch_playwright_snippets():
        headlines.append(
            {"title": extra.get("title", "web"), "link": extra.get("link", ""), "excerpt": extra.get("body_excerpt", "")}
        )
    business = _business_snapshot_excerpt(oid)
    correlated = _groq_correlate(business=business, headlines=headlines)
    ts = time.time()
    record: dict[str, Any] = {
        "ts": ts,
        "organization_id": oid,
        "headline_count": len(headlines),
        "headlines_sample": headlines[:12],
        "correlation": correlated,
    }
    append_world_scan_record(oid, record)
    record_background_action(
        category="world_scan",
        summary=(correlated.get("summary") or f"Scanned {len(headlines)} headlines")[:1900],
        organization_id=oid,
        meta={"proposals": correlated.get("strategic_proposals") or []},
    )
    record_cot_step(
        agent="world_scanner",
        phase="complete",
        detail=(correlated.get("summary") or "")[:2000],
        organization_id=oid,
    )
    return {"ok": True, "organization_id": oid, "headlines": len(headlines), "correlation": correlated}


def recent_world_events(organization_id: int, *, limit: int = 20) -> list[dict[str, Any]]:
    path = _events_path(int(organization_id))
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
