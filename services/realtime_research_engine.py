"""
Real-time research engine: world intelligence collection + mission mapping.

Read-only intelligence layer: no execution side-effects beyond best-effort signal fetch.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any

import httpx

from services.identity_context_loader import (
    compute_identity_influence,
    load_master_identity_context,
    score_long_term_alignment,
)
from services.world_scanner import recent_world_events, run_world_scan_for_org


def _to_text(v: Any, n: int = 320) -> str:
    return str(v or "").strip().replace("\n", " ")[:n]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _domain_for_text(text: str) -> str:
    t = str(text or "").lower()
    if any(k in t for k in ("robot", "humanoid", "automation", "factory bot")):
        return "robotics"
    if any(k in t for k in ("chip", "semiconductor", "gpu", "cpu", "wafer")):
        return "chips"
    if any(k in t for k in ("energy", "battery", "solar", "nuclear", "grid", "fusion")):
        return "energy"
    if any(k in t for k in ("ai", "llm", "model", "agent", "open-source", "opensource")):
        return "ai"
    return "business"


def _importance(text: str) -> float:
    t = str(text or "").lower()
    score = 0.42
    if any(k in t for k in ("launch", "release", "breakthrough", "funding", "acquisition", "regulation", "ban")):
        score += 0.20
    if any(k in t for k in ("ai", "chip", "robot", "energy")):
        score += 0.16
    if any(k in t for k in ("open-source", "opensource", "startup")):
        score += 0.08
    return round(max(0.0, min(1.0, score)), 4)


def _as_update(row: dict[str, Any], identity_ctx: dict[str, Any]) -> dict[str, Any]:
    title = _to_text(row.get("title") or row.get("headline") or row.get("summary"))
    domain = _domain_for_text(title)
    align = score_long_term_alignment(title, identity_ctx)
    source = _to_text(row.get("source") or row.get("feed") or "world_events", 120)
    timestamp = _to_text(row.get("timestamp") or row.get("published_at") or row.get("published") or _now_iso(), 80)
    confidence = float(row.get("confidence")) if isinstance(row.get("confidence"), (int, float)) else 0.62
    importance = _importance(title)
    actionability = max(0.0, min(1.0, (0.45 * importance) + (0.30 * float(confidence)) + (0.25 * float(align))))
    return {
        "title": title,
        "link": _to_text(row.get("link"), 600),
        "domain": domain,
        "what_changed": title,
        "why_important": f"{domain} signal may shift competitive positioning and capability timing.",
        "who_benefits": "Early movers with fast execution loops and mission-aligned capital.",
        "importance": importance,
        "mission_alignment": round(align, 4),
        "source": source,
        "timestamp": timestamp,
        "confidence": round(max(0.0, min(1.0, confidence)), 4),
        "opportunity_score": round(max(0.0, min(1.0, (0.55 * importance) + (0.45 * float(align)))), 4),
        "actionability_score": round(actionability, 4),
    }


def _fallback_updates(identity_ctx: dict[str, Any]) -> list[dict[str, Any]]:
    seeds = [
        "AI model release cadence is accelerating for enterprise copilots.",
        "Robotics integration costs are dropping in industrial automation pilots.",
        "Energy storage innovation is improving grid and factory resilience.",
    ]
    out = []
    for s in seeds:
        imp = _importance(s)
        align = score_long_term_alignment(s, identity_ctx)
        out.append({
            "title": s,
            "link": "",
            "domain": _domain_for_text(s),
            "what_changed": s,
            "why_important": "Baseline strategic signal when live feed is sparse.",
            "who_benefits": "Operators converting signals into measurable execution advantages.",
            "importance": imp,
            "mission_alignment": align,
            "source": "fallback_seed",
            "timestamp": _now_iso(),
            "confidence": 0.45,
            "opportunity_score": round(max(0.0, min(1.0, (0.55 * imp) + (0.45 * align))), 4),
            "actionability_score": round(max(0.0, min(1.0, (0.45 * imp) + (0.30 * 0.45) + (0.25 * align))), 4),
        })
    return out


def convert_research_to_opportunities(realtime_output: dict[str, Any]) -> list[dict[str, Any]]:
    updates = [u for u in list((realtime_output or {}).get("daily_updates") or []) if isinstance(u, dict)]
    out: list[dict[str, Any]] = []
    for u in updates[:12]:
        title = _to_text(u.get("title"), 200)
        if not title:
            continue
        domain = _to_text(u.get("domain") or "business", 80)
        mission_alignment = float(u.get("mission_alignment") or 0.0)
        opp_score = float(u.get("opportunity_score") or 0.0)
        actionability = float(u.get("actionability_score") or 0.0)
        confidence = float(u.get("confidence") or 0.5)
        urgency = float(u.get("importance") or 0.5)
        expected_value = round(max(0.0, min(1.0, (0.45 * opp_score) + (0.30 * mission_alignment) + (0.25 * confidence))), 4)
        risk = round(max(0.05, min(0.85, 0.55 - (0.40 * actionability))), 4)
        safe = bool(risk < 0.65 and actionability >= 0.45)
        out.append(
            {
                "title": f"{domain.upper()} opportunity: {title}",
                "why_now": "Signal freshness + alignment indicate near-term strategic value.",
                "expected_value": expected_value,
                "execution_path": [
                    "Create a short internal brief with assumptions and constraints.",
                    "Run a low-risk validation experiment.",
                    "Escalate to value/result engine if metrics confirm upside.",
                ],
                "risk": risk,
                "mission_alignment": round(mission_alignment, 4),
                "urgency": round(urgency, 4),
                "roi_potential": round(max(0.0, min(1.0, expected_value + 0.08)), 4),
                "opportunity_score": round(max(0.0, min(1.0, opp_score)), 4),
                "actionability_score": round(max(0.0, min(1.0, actionability)), 4),
                "safe_to_execute": safe,
                "assist_required": bool(not safe),
                "source": _to_text(u.get("source"), 120),
                "timestamp": _to_text(u.get("timestamp"), 80),
                "confidence": round(max(0.0, min(1.0, confidence)), 4),
            }
        )
    out.sort(
        key=lambda x: float(
            (0.40 * float(x.get("opportunity_score") or 0.0))
            + (0.30 * float(x.get("actionability_score") or 0.0))
            + (0.30 * float(x.get("mission_alignment") or 0.0))
        ),
        reverse=True,
    )
    return out[:8]


def _safe_get_json(url: str, *, timeout: float = 15.0, params: dict[str, Any] | None = None) -> Any:
    headers = {
        "User-Agent": "THIRAMAI-LiveResearch/1.0",
        "Accept": "application/json",
    }
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        res = client.get(url, params=params or {}, headers=headers)
        res.raise_for_status()
        return res.json()


def fetch_live_world_data() -> dict[str, list[dict[str, Any]]]:
    """
    Live, read-only connectors for external intelligence.
    Falls back gracefully on per-source failures.
    """
    out: dict[str, list[dict[str, Any]]] = {
        "ai_updates": [],
        "tech_news": [],
        "open_source": [],
        "hardware": [],
        "startup_launches": [],
    }

    # 1) Tech / AI / startup launches: Hacker News front page (live)
    try:
        ids = _safe_get_json("https://hacker-news.firebaseio.com/v0/topstories.json")
        if isinstance(ids, list):
            for sid in ids[:20]:
                item = _safe_get_json(f"https://hacker-news.firebaseio.com/v0/item/{int(sid)}.json")
                if not isinstance(item, dict):
                    continue
                title = _to_text(item.get("title"), 260)
                if not title:
                    continue
                row = {
                    "title": title,
                    "link": _to_text(item.get("url") or f"https://news.ycombinator.com/item?id={item.get('id')}", 600),
                    "source": "hackernews",
                    "timestamp": _now_iso(),
                    "confidence": 0.74,
                }
                t = title.lower()
                out["tech_news"].append(row)
                if any(k in t for k in ("ai", "llm", "model", "agent", "gpt", "anthropic", "openai")):
                    out["ai_updates"].append(row)
                if any(k in t for k in ("startup", "launch", "raised", "funding", "product")):
                    out["startup_launches"].append(row)
                if any(k in t for k in ("chip", "gpu", "semiconductor", "nvidia", "wafer", "hardware")):
                    out["hardware"].append(row)
    except Exception:
        pass

    # 2) Open-source releases: GitHub public events (live, read-only)
    try:
        events = _safe_get_json("https://api.github.com/events", timeout=20.0)
        if isinstance(events, list):
            for ev in events[:40]:
                if not isinstance(ev, dict):
                    continue
                ev_type = _to_text(ev.get("type"), 80)
                repo = _to_text((ev.get("repo") or {}).get("name"), 180) if isinstance(ev.get("repo"), dict) else ""
                payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
                title = ""
                if ev_type == "ReleaseEvent":
                    rel = payload.get("release") if isinstance(payload.get("release"), dict) else {}
                    title = _to_text(rel.get("name") or rel.get("tag_name") or f"Release: {repo}", 240)
                elif ev_type == "PushEvent":
                    title = f"Push update in {repo}"
                elif ev_type == "CreateEvent":
                    title = f"Create event in {repo}"
                if not title:
                    continue
                out["open_source"].append(
                    {
                        "title": title,
                        "link": f"https://github.com/{repo}" if repo else "https://github.com",
                        "source": "github_events",
                        "timestamp": _to_text(ev.get("created_at") or _now_iso(), 80),
                        "confidence": 0.7 if ev_type == "ReleaseEvent" else 0.56,
                    }
                )
    except Exception:
        pass

    # 3) Hardware/chip and general tech backup via existing RSS config (live endpoint call)
    try:
        rss = (os.getenv("THIRAMAI_WORLD_RSS_FEEDS") or "").strip()
        if rss:
            first = [x.strip() for x in rss.split(",") if x.strip().startswith("http")]
        else:
            first = ["https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"]
        for u in first[:2]:
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                r = client.get(u, headers={"User-Agent": "THIRAMAI-LiveResearch/1.0"})
                r.raise_for_status()
                txt = r.text[:300000]
            # Lightweight title extraction for RSS without extra dependencies.
            parts = txt.split("<title>")
            for p in parts[1:12]:
                t = _to_text(p.split("</title>")[0], 220)
                if not t or "Google News" in t:
                    continue
                row = {"title": t, "link": u, "source": "rss_live", "timestamp": _now_iso(), "confidence": 0.58}
                out["tech_news"].append(row)
                if any(k in t.lower() for k in ("chip", "gpu", "semiconductor", "hardware", "wafer")):
                    out["hardware"].append(row)
                if any(k in t.lower() for k in ("ai", "llm", "model", "agent")):
                    out["ai_updates"].append(row)
    except Exception:
        pass

    # De-duplicate per bucket by title.
    for k, rows in out.items():
        seen: set[str] = set()
        uniq: list[dict[str, Any]] = []
        for row in rows:
            key = _to_text((row or {}).get("title"), 180).lower()
            if not key or key in seen:
                continue
            seen.add(key)
            uniq.append(row)
        out[k] = uniq[:12]
    return out


def run_realtime_research_cycle(user_id: int, organization_id: int) -> dict[str, Any]:
    _ = int(user_id)
    oid = int(organization_id)
    identity_ctx = load_master_identity_context()

    # Best-effort refresh; ignore failures and fall back to recent persisted events.
    try:
        run_world_scan_for_org(oid)
    except Exception:
        pass
    events = recent_world_events(oid, limit=12)
    live = fetch_live_world_data()
    headlines: list[dict[str, Any]] = []
    for bucket in ("ai_updates", "tech_news", "open_source", "hardware", "startup_launches"):
        for row in list(live.get(bucket) or []):
            if isinstance(row, dict):
                headlines.append(row)
    for e in events:
        sample = list((e.get("headlines_sample") if isinstance(e.get("headlines_sample"), list) else []) or [])
        for row in sample:
            if isinstance(row, dict):
                headlines.append(row)
    updates = [_as_update(x, identity_ctx) for x in headlines[:24] if isinstance(x, dict)]
    if not updates:
        updates = _fallback_updates(identity_ctx)

    opportunities: list[dict[str, Any]] = []
    threats: list[dict[str, Any]] = []
    recommended_actions: list[dict[str, Any]] = []
    mission_links: list[dict[str, Any]] = []

    for u in updates[:10]:
        title = str(u.get("title") or "")
        domain = str(u.get("domain") or "business")
        align = float(u.get("mission_alignment") or 0.0)
        importance = float(u.get("importance") or 0.5)
        identity_influence = compute_identity_influence(
            mission_alignment_score=align,
            long_term_alignment=align,
            identity_ctx=identity_ctx,
        )
        if importance >= 0.60:
            opportunities.append(
                {
                    "title": f"Exploit {domain} signal: {title[:160]}",
                    "domain": domain,
                    "priority": round((0.6 * importance) + (0.4 * align), 4),
                    "why_now": "Signal strength and timing favor early strategic positioning.",
                }
            )
        if any(k in title.lower() for k in ("ban", "regulation", "price spike", "shortage", "delay", "lawsuit")):
            threats.append(
                {
                    "title": f"Risk watch: {title[:170]}",
                    "domain": domain,
                    "severity": "high" if importance > 0.7 else "medium",
                    "impact": "Potential disruption to roadmap, cost, or speed.",
                }
            )
        recommended_actions.append(
            {
                "title": f"Create a 48h brief for {domain} signal",
                "domain": domain,
                "safe_to_execute": True,
                "assist_required": False,
                "action_type": "intelligence_brief_only",
                "rationale": "Convert world signal into concrete internal options before competitors.",
            }
        )
        mission_links.append(
            {
                "signal": title[:180],
                "mission_link": f"Supports long-term capability in {domain} if validated quickly.",
                "alignment_score": round(align, 4),
                "identity_influence": round(identity_influence, 4),
            }
        )

    # Keep concise, non-empty result.
    if not opportunities:
        opportunities = [
            {
                "title": "Opportunity pipeline from AI/robotics/energy watchlist",
                "domain": "ai",
                "priority": 0.62,
                "why_now": "Maintains proactive opportunity capture even on low-signal days.",
            }
        ]
    if not threats:
        threats = [
            {
                "title": "No acute threat spike detected; continue monitoring cost/regulation shifts.",
                "domain": "business",
                "severity": "low",
                "impact": "Baseline monitoring state.",
            }
        ]

    provisional = {
        "daily_updates": updates[:8],
        "opportunities": opportunities[:6],
        "threats": threats[:6],
        "recommended_actions": recommended_actions[:8],
        "mission_links": mission_links[:8],
    }
    activated = convert_research_to_opportunities(provisional)

    return {
        **provisional,
        "activated_opportunities": activated,
        "live_sources": {
            "ai_updates": len(list(live.get("ai_updates") or [])),
            "tech_news": len(list(live.get("tech_news") or [])),
            "open_source": len(list(live.get("open_source") or [])),
            "hardware": len(list(live.get("hardware") or [])),
            "startup_launches": len(list(live.get("startup_launches") or [])),
        },
    }

