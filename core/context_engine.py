"""
Council / orchestrator context: vault retrieval, executive pack, shared core for Groq rounds.

Distinct from ``core.personal_life_context`` (Personal OS director modes).
"""

from __future__ import annotations

from typing import Any

import executive_core


def load_vault_context_safe(
    raw: str,
    *,
    max_chars: int | None = None,
    organization_id: int,
) -> str:
    """Tenant-scoped vault excerpts; soft-fail to a short message on errors."""
    try:
        import vault_memory

        cap = 8000 if max_chars is None else int(max_chars)
        return vault_memory.build_vault_context(
            raw or "",
            max_chars=max(500, cap),
            organization_id=int(organization_id),
        )
    except Exception as exc:
        return f"_Vault context unavailable ({type(exc).__name__})._"


def enrich_vault_for_query(raw: str, vault_ctx: str, organization_id: int) -> str:
    """Append light R&D core slice for the tenant when available."""
    oid = int(organization_id)
    if oid <= 0 or not (vault_ctx or "").strip():
        return vault_ctx
    try:
        import vault_memory

        rd = vault_memory.load_rd_core_context(max_chars=2200, organization_id=oid)
        if rd and str(rd).strip():
            return vault_ctx + "\n\n### R&D core (tenant vault)\n\n" + str(rd).strip()
    except Exception:
        pass
    return vault_ctx


def vault_priority_search_context() -> tuple[str, bool]:
    """
    When personal-vault routing skips Tavily, use profile + persisted agenda as the context block.
    """
    try:
        executive_core.ensure_vault()
        blk = (
            executive_core.format_user_profile_block()
            + "\n\n"
            + executive_core.format_empire_agenda_block()
        ).strip()
        return blk, bool(blk)
    except Exception:
        return "(Personal vault context unavailable.)", False


def _stress_late_hints(raw: str) -> tuple[bool, bool]:
    t = (raw or "").lower()
    stress = any(
        k in t
        for k in (
            "stress",
            "stressed",
            "exhausted",
            "burnout",
            "overwhelmed",
            "anxious",
            "can't sleep",
            "cant sleep",
        )
    )
    late = any(
        k in t for k in ("2am", "3am", "4am", "5am", "midnight", "late night", "all-nighter", "still working")
    )
    return stress, late


def build_executive_pack(
    raw: str,
    vault_ctx: str,
    *,
    organization_id: int,
    user_id: int | None = None,
    vault_passphrase: str | None = None,
) -> str:
    """Markdown situational pack for the CEO executive pass."""
    from services.daily_flow import append_life_os_if_relevant

    stress_hint, late_hint = _stress_late_hints(raw)
    parts: list[str] = [
        "## Indexed Knowledge Vault (tenant)\n" + (vault_ctx or "_empty_"),
        executive_core.format_user_profile_block(),
        executive_core.format_empire_agenda_block(),
        executive_core.format_health_reminder_block(stress_hint, late_hint),
    ]
    life = append_life_os_if_relevant(
        raw,
        organization_id=int(organization_id),
        user_id=int(user_id) if user_id is not None and int(user_id) > 0 else None,
        vault_passphrase=(vault_passphrase or "").strip() or None,
    )
    if life and str(life).strip():
        parts.append(str(life).strip())
    return "\n\n".join(parts)


def build_shared_core(
    *,
    ceo_brief: str,
    vault_ctx: str,
    saas_preview: str,
    raw: str,
    context_block: str,
    planning_note: str,
    personal_vault: bool,
) -> str:
    """Single markdown bundle for industrial / strategic / personal councils."""
    _ = raw
    _ = personal_vault
    parts = [
        "## CEO executive preamble\n" + (ceo_brief or "").strip(),
        "## Live retrieval / web context\n" + (context_block or "_none_").strip(),
        "## Knowledge Vault (indexed)\n" + (vault_ctx or "_none_").strip(),
        "## Planning & factory appendix\n" + (planning_note or "").strip(),
        "## SaaS factory preview\n" + (saas_preview or "").strip(),
    ]
    return "\n\n".join(parts)
