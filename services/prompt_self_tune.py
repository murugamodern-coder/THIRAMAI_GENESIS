"""
Recursive prompt engineering: measure loaded policy prompt sizes and ask Groq for
token/latency-focused refinement suggestions (audit trail only — human merges to ``core/policies``).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from core.policies import loader as policy_loader
from core.recursive_learning import V2_PATH
from core.sovereign_journal import record_background_action, record_cot_step

_LOG = __import__("logging").getLogger(__name__)


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _audit_dir() -> Path:
    d = _root() / "var" / "sovereign" / "prompt_tuning"
    d.mkdir(parents=True, exist_ok=True)
    return d


def collect_prompt_inventory() -> dict[str, Any]:
    """Character counts per ``get_prompt`` section + v2 tail size."""
    sections = policy_loader._prompt_sections()  # noqa: SLF001 — intentional introspection
    sizes = {k: len(v) for k, v in sections.items()}
    v2_chars = len(V2_PATH.read_text(encoding="utf-8")) if V2_PATH.is_file() else 0
    total = sum(sizes.values())
    return {
        "policy_version": policy_loader.policy_version(),
        "section_chars": sizes,
        "sections_total_chars": total,
        "prompts_v2_chars": v2_chars,
        "largest_sections": sorted(sizes.items(), key=lambda x: -x[1])[:12],
    }


def run_prompt_self_analysis(*, organization_id: int | None = None) -> dict[str, Any]:
    inv = collect_prompt_inventory()
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    suggestions = ""
    if key:
        from groq import Groq

        prompt = (
            "You optimize LLM system prompts for lower token use and clearer reasoning. "
            "Given INVENTORY JSON (section sizes), propose concrete edits: merge redundant sections, "
            "move examples to appendix, tighten instructions. Output Markdown max 3500 chars — no full rewrites, "
            "only numbered actionable suggestions referencing section NAMES.\n\n"
            f"INVENTORY:\n{json.dumps(inv, indent=2)[:12000]}"
        )
        try:
            client = Groq(api_key=key)
            chat = client.chat.completions.create(
                model=(os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile").strip(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.25,
                max_tokens=4000,
            )
            suggestions = (chat.choices[0].message.content or "").strip()
        except Exception as exc:
            suggestions = f"_Analysis failed: {type(exc).__name__}: {exc}_"
            _LOG.warning("prompt_self_tune: groq failed: %s", exc)
    else:
        suggestions = "_Set GROQ_API_KEY for AI suggestions; inventory still recorded._"

    row = {
        "ts": time.time(),
        "organization_id": organization_id,
        "inventory": inv,
        "suggestions_markdown": suggestions,
    }
    line = json.dumps(row, ensure_ascii=False, default=str) + "\n"
    oid = int(organization_id) if organization_id is not None else None
    try:
        suffix = f"org_{oid}" if oid is not None else "global"
        with (_audit_dir() / f"{suffix}.jsonl").open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError as exc:
        _LOG.warning("prompt_self_tune: persist failed: %s", exc)

    record_cot_step(
        agent="prompt_self_tune",
        phase="analysis",
        detail=f"sections_total_chars={inv.get('sections_total_chars')}",
        organization_id=oid,
    )
    record_background_action(
        category="prompt_tuning",
        summary=suggestions[:1900],
        organization_id=oid,
        meta={"sections_total": inv.get("sections_total_chars")},
    )
    return row


def latest_prompt_audit(*, organization_id: int | None = None) -> dict[str, Any] | None:
    suffix = f"org_{int(organization_id)}" if organization_id is not None else "global"
    path = _audit_dir() / f"{suffix}.jsonl"
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
