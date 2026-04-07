"""
Stage 5 — Minute Office: roll up background actions + world scans into one daily executive narrative.

Target: ~14-minute read (roughly 2.8k–3.5k words max cap). Sections:
  What I saw | What I changed in code | What I fixed in the factory | What you need to know
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from core.sovereign_journal import read_action_trail_since, sovereign_stage5_enabled
from services.world_scanner import recent_world_events

_LOG = __import__("logging").getLogger(__name__)


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _summary_path(organization_id: int) -> Path:
    d = _root() / "var" / "sovereign" / "executive_summaries"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"org_{int(organization_id)}.jsonl"


def append_executive_summary(organization_id: int, *, markdown: str, meta: dict[str, Any]) -> None:
    row = {
        "ts": time.time(),
        "organization_id": int(organization_id),
        "markdown": markdown,
        "meta": meta,
    }
    line = json.dumps(row, ensure_ascii=False, default=str) + "\n"
    try:
        sp = _summary_path(int(organization_id))
        with sp.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError as exc:
        _LOG.warning("task_aggregator: write summary failed: %s", exc)


def latest_executive_summary(organization_id: int) -> dict[str, Any] | None:
    path = _summary_path(int(organization_id))
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


def _bucket_actions(actions: list[dict[str, Any]]) -> dict[str, list[str]]:
    buckets = {
        "code": [],
        "factory": [],
        "world": [],
        "ops": [],
        "other": [],
    }
    for a in actions:
        cat = (a.get("category") or "other").lower()
        s = (a.get("summary") or "").strip()
        if not s:
            continue
        if cat in ("world_scan", "world"):
            buckets["world"].append(s[:500])
        elif cat in ("kernel", "sandbox", "self_coder", "code", "ltm"):
            buckets["code"].append(s[:500])
        elif cat in ("factory", "project", "stage2"):
            buckets["factory"].append(s[:500])
        elif cat in ("job_queue", "billing", "inventory"):
            buckets["ops"].append(s[:500])
        else:
            buckets["other"].append(f"[{cat}] {s[:480]}")
    return buckets


def build_daily_executive_summary(
    organization_id: int,
    *,
    period_seconds: int = 86_400,
) -> str:
    """Synthesize markdown from trail + world events; uses Groq when configured."""
    if not sovereign_stage5_enabled():
        return ""
    now = time.time()
    since = now - int(period_seconds)
    actions = read_action_trail_since(since_ts=since, limit=5000, organization_id=int(organization_id))
    worlds = recent_world_events(int(organization_id), limit=8)
    buckets = _bucket_actions(actions)

    def _collapse(lines: list[str], cap: int = 40) -> str:
        if not lines:
            return "_No entries in this window._"
        return "\n".join(f"- {t}" for t in lines[:cap])

    if len(actions) > 1000:
        note = f"_Note: {len(actions)} background actions in window; showing representative buckets._\n\n"
    else:
        note = ""

    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not key:
        world_lines = list(buckets["world"])
        for w in worlds:
            if isinstance(w, dict):
                s = str((w.get("correlation") or {}).get("summary") or "").strip()
                if s:
                    world_lines.append(s)
        md = (
            f"# Executive summary (org {organization_id})\n\n"
            f"{note}"
            "## What I saw\n"
            f"{_collapse(world_lines)}\n\n"
            "## What I changed in my code\n"
            f"{_collapse(buckets['code'])}\n\n"
            "## What I fixed in the factory\n"
            f"{_collapse(buckets['factory'])}\n\n"
            "## What you need to know\n"
            f"{_collapse(buckets['ops'] + buckets['other'])}\n"
        )
        append_executive_summary(
            int(organization_id),
            markdown=md,
            meta={"mode": "deterministic", "action_count": len(actions)},
        )
        return md

    from groq import Groq

    payload = {
        "action_count": len(actions),
        "code": buckets["code"][:80],
        "factory": buckets["factory"][:80],
        "world": buckets["world"][:40],
        "ops": buckets["ops"][:80],
        "other": buckets["other"][:40],
        "world_scan_snips": [
            (w.get("correlation") or {}).get("summary", "") for w in worlds if isinstance(w, dict)
        ][:6],
    }
    prompt = (
        "You are THIRAMAI's sovereign chief of staff. Write a single Markdown executive brief for the business owner. "
        "Use exactly these H2 sections in order:\n"
        "## What I saw\n## What I changed in my code\n## What I fixed in the factory\n## What you need to know\n\n"
        "Tone: precise, non-hype. If a section has no data, say so briefly. "
        f"Aim for a ~12–15 minute read (about 2500–3200 words max). JSON input:\n{json.dumps(payload, ensure_ascii=False)[:24000]}"
    )
    try:
        client = Groq(api_key=key)
        chat = client.chat.completions.create(
            model=(os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile").strip(),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.25,
            max_tokens=8000,
        )
        md = (chat.choices[0].message.content or "").strip()
        if not md.startswith("#"):
            md = "# Executive summary\n\n" + md
    except Exception as exc:
        _LOG.warning("task_aggregator: groq failed: %s", exc)
        md = f"# Executive summary\n\n_Generation error: {type(exc).__name__}_\n"
    append_executive_summary(
        int(organization_id),
        markdown=md,
        meta={"mode": "groq", "action_count": len(actions)},
    )
    return md
