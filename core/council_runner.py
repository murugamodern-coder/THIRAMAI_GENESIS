"""Multi-agent councils, industrial DPR loop, Tamil repair — uses policies + ToolRegistry."""

from __future__ import annotations

from groq import Groq

from core.errors import QueryLengthExceeded, looks_like_length_limit_error
from core.observability import log_structured
from core.policies.loader import (
    _CEO_MAX_TOKENS,
    _COUNCIL_PRIOR_CLIP,
    _MAX_TOKENS,
    get_prompt,
)
from tools.registry import ToolRegistry


def _ascii_debug(s: str, max_chars: int = 160) -> str:
    return ascii((s or "")[:max_chars])


def tamil_watch_violations(text: str) -> bool:
    from core.policies.loader import _MAX_WATCH_WORD, _TAMIL_WORDS

    for w in _TAMIL_WORDS:
        if text.count(w) > _MAX_WATCH_WORD:
            return True
    return False


def merge_user_structured_envelope(body: str) -> str:
    """Append JSON envelope contract so the synthesizer returns narrative + action_intent."""
    return f"{body.rstrip()}\n\n## Structured output (mandatory)\n\n{get_prompt('STRUCTURED_OUTPUT_ENVELOPE')}"


def clip_prior(text: str) -> str:
    t = (text or "").strip()
    if len(t) <= _COUNCIL_PRIOR_CLIP:
        return t
    return t[:_COUNCIL_PRIOR_CLIP] + "\n\n[... truncated for context ...]"


def groq_completion_single(
    registry: ToolRegistry,
    client: Groq,
    system: str,
    user: str,
    *,
    max_tokens: int | None = None,
    event_suffix: str = "council",
) -> str:
    anti = get_prompt("ANTI_REPEAT")
    completion = registry.groq_chat_completions_create(
        client,
        messages=[
            {"role": "system", "content": f"{system}\n\n{anti}"},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens if max_tokens is not None else _MAX_TOKENS,
        event_label=f"groq.{event_suffix}",
    )
    choice = completion.choices[0].message.content
    return (choice or "").strip()


def round_prompts_industrial_dpr(shared_core: str) -> tuple[str, str, str]:
    ar = get_prompt("ANTI_REPEAT")
    r1_body = get_prompt("INDUSTRIAL_DPR_ROUND1_SUFFIX").format(anti_repeat=ar)
    r2_body = get_prompt("INDUSTRIAL_DPR_ROUND2_USER").format(anti_repeat=ar)
    r3_body = get_prompt("INDUSTRIAL_DPR_ROUND3_USER").format(anti_repeat=ar)
    r1 = f"{shared_core}\n\n{r1_body}"
    return r1, r2_body, r3_body


def repair_tamil_and_fluff(
    registry: ToolRegistry, client: Groq, system_content: str, report: str
) -> str:
    prefix = get_prompt("TAMIL_REPAIR_USER_PREFIX")
    fix_user = f"{prefix}\n\n{report}"
    completion = registry.groq_chat_completions_create(
        client,
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": fix_user},
        ],
        temperature=0.25,
        max_tokens=_MAX_TOKENS,
        event_label="groq.tamil_repair",
    )
    out = completion.choices[0].message.content
    cleaned = (out or "").strip()
    return cleaned if cleaned else report


def run_ceo_executive_pass(
    registry: ToolRegistry, client: Groq, raw: str, executive_pack: str
) -> str:
    user = f"""## Situational pack (Knowledge Vault index + persisted agenda + signals)
{executive_pack}

## User message (verbatim)
{raw}

Produce the CEO executive preamble only (Empire Agenda + Health Guard + task categories)."""
    try:
        out = groq_completion_single(
            registry,
            client,
            get_prompt("PROMPT_CEO_AGENT"),
            user,
            max_tokens=_CEO_MAX_TOKENS,
            event_suffix="ceo",
        )
        return out if out else "## Empire Agenda (Today)\n- (Empty CEO response)\n"
    except Exception as exc:
        if looks_like_length_limit_error(exc):
            raise QueryLengthExceeded(
                "The model request was too long for the provider (CEO pass). "
                "Try a shorter brief (under 5000 characters) or narrow the topic."
            ) from exc
        log_structured(
            "council_runner.ceo_executive_pass_failed",
            error=_ascii_debug(str(exc), 240),
            fallback="stub_agenda",
        )
        return (
            "## Empire Agenda (Today)\n"
            "- CEO brief unavailable; refer to Knowledge Vault and persisted agenda in context.\n"
        )


def _council_handle_exc(round_name: str, exc: BaseException) -> None:
    if looks_like_length_limit_error(exc):
        raise QueryLengthExceeded(
            "The model request was too long for the provider. "
            "Try a shorter brief (under 5000 characters) or narrow the topic."
        ) from exc


def run_strategic_council(registry: ToolRegistry, client: Groq, shared_core: str) -> str:
    r1_user = f"""{shared_core}

## Council Round 1 - Field Intelligence (Agri-Scientist)
Analyze the user request and LIVE SEARCH results. Output **biological and environmental constraints** only: botany, soil health, yield optimization, climate resilience - the **What & Where** of the crop. No financial tables or tech roadmap here.
"""
    try:
        r1 = groq_completion_single(
            registry, client, get_prompt("PROMPT_AGRI_SCIENTIST"), r1_user, event_suffix="council_r1"
        )
    except Exception as exc:
        _council_handle_exc("r1", exc)
        log_structured(
            "council_runner.agri_r1_stub",
            error=_ascii_debug(str(exc), 200),
        )
        r1 = "**Partial:** Field Intelligence unavailable; use LIVE SEARCH + vault for agronomy."

    if not r1:
        return "**Awaiting Live Data** - Field Intelligence (Agri-Scientist) returned an empty response."

    r2_user = f"""{shared_core}

## Prior output - Round 1 Field Intelligence (Agri-Scientist)
{clip_prior(r1)}

## Council Round 2 - Financial Engine (Economic Architect)
Using the biological context above plus LIVE SEARCH, produce **Cost & Profit**: INR financial modeling, CAPEX, OPEX, ROI, market and supply chain. Detailed financial tables and market analysis. Do not replace Round 1 with full agronomy or add the full tech roadmap.
"""
    try:
        r2 = groq_completion_single(
            registry,
            client,
            get_prompt("PROMPT_ECONOMIC_ARCHITECT"),
            r2_user,
            event_suffix="council_r2",
        )
    except Exception as exc:
        _council_handle_exc("r2", exc)
        log_structured(
            "council_runner.agri_r2_stub",
            error=_ascii_debug(str(exc), 200),
        )
        r2 = "_Financial Engine unavailable; synthesize from Field Intelligence only._"

    if not r2:
        r2 = "_Financial Engine (Economic Architect) returned empty; synthesize from Field Intelligence only._"

    r3_user = f"""{shared_core}

## Round 1 - Field Intelligence (Agri-Scientist)
{clip_prior(r1)}

## Round 2 - Financial Engine (Economic Architect)
{clip_prior(r2)}

## Council Round 3 - Tech Integration (Tech Strategist)
Integrate R1 and R2. Deliver **How & Future-Proofing**: AI, humanoid robotics (Optimus/Digit if relevant), drones, IoT. Output **THIRAMAI 2026 Technology Roadmap and Automation Plan**. Do not re-issue full financial tables or full soil monographs.
"""
    try:
        r3 = groq_completion_single(
            registry,
            client,
            get_prompt("PROMPT_TECH_STRATEGIST"),
            r3_user,
            event_suffix="council_r3",
        )
    except Exception as exc:
        _council_handle_exc("r3", exc)
        log_structured(
            "council_runner.agri_r3_stub",
            error=_ascii_debug(str(exc), 200),
        )
        r3 = "_Tech Integration unavailable._"

    if not r3:
        r3 = "_Tech Integration (Tech Strategist) returned empty._"

    merge_user = f"""Merge the three expert sections below into **one** Markdown document titled **THIRAMAI TECH EMPIRE: SOVEREIGN STRATEGY BRIEF** (see SYNTHESIS_SYSTEM for exact H1 and H2 structure).

### Source - Round 1 Field Intelligence (Agri-Scientist)
{clip_prior(r1)}

### Source - Round 2 Financial Engine (Economic Architect)
{clip_prior(r2)}

### Source - Round 3 Tech Integration (Tech Strategist)
{clip_prior(r3)}
"""
    merge_user = merge_user_structured_envelope(merge_user)
    try:
        final = groq_completion_single(
            registry,
            client,
            get_prompt("SYNTHESIS_SYSTEM"),
            merge_user,
            event_suffix="council_merge",
        )
    except Exception as exc:
        _council_handle_exc("merge", exc)
        log_structured(
            "council_runner.agri_synthesis_stub",
            error=_ascii_debug(str(exc), 200),
        )
        final = ""

    if final and len(final) > 200:
        return final
    return (
        "THIRAMAI 2026 STRATEGY ANALYSIS\n\n"
        "# THIRAMAI TECH EMPIRE: SOVEREIGN STRATEGY BRIEF\n\n"
        + r1
        + "\n\n---\n\n"
        + r2
        + "\n\n---\n\n"
        + r3
    )


def run_manufacturing_empire_council(registry: ToolRegistry, client: Groq, shared_core: str) -> str:
    r1_user = f"""{shared_core}

## Council Round 1 - Manufacturing & Industrial Operations
Use KNOWLEDGE VAULT for this user's plant and priorities. Output **manufacturing** operations analysis only (no default agriculture).
"""
    try:
        r1 = groq_completion_single(
            registry,
            client,
            get_prompt("PROMPT_MANUFACTURING_OPS"),
            r1_user,
            event_suffix="mfg_r1",
        )
    except Exception as exc:
        _council_handle_exc("mfg_r1", exc)
        log_structured("council_runner.manufacturing_r1_stub", error=_ascii_debug(str(exc), 200))
        r1 = "**Partial:** Manufacturing round unavailable; use vault context."

    if not r1:
        return "**Awaiting Live Data** - Manufacturing round returned an empty response."

    r2_user = f"""{shared_core}

## Prior output - Round 1 Manufacturing & Industrial Operations
{clip_prior(r1)}

## Council Round 2 - Financial Engine (savings, runway, cash flow)
Focus on **INR runway**, savings buffer, revenue gaps, GST/compliance — from vault and Round 1. No agronomy.
"""
    try:
        r2 = groq_completion_single(
            registry,
            client,
            get_prompt("PROMPT_ECONOMIC_RUNWAY"),
            r2_user,
            event_suffix="mfg_r2",
        )
    except Exception as exc:
        _council_handle_exc("mfg_r2", exc)
        log_structured("council_runner.manufacturing_r2_stub", error=_ascii_debug(str(exc), 200))
        r2 = "_Financial Engine returned empty; synthesize from Manufacturing round only._"

    if not r2:
        r2 = "_Financial Engine returned empty; synthesize from Manufacturing round only._"

    r3_user = f"""{shared_core}

## Round 1 - Manufacturing & Industrial Operations
{clip_prior(r1)}

## Round 2 - Financial Engine (Economic Architect)
{clip_prior(r2)}

## Council Round 3 - Tech Integration (CRM, SaaS, access)
Deliver **SaaS / CRM / digital ops** aligned to vault blockers. No full agronomy or duplicate financial tables.
"""
    try:
        r3 = groq_completion_single(
            registry,
            client,
            get_prompt("PROMPT_TECH_SAAS_CRM"),
            r3_user,
            event_suffix="mfg_r3",
        )
    except Exception as exc:
        _council_handle_exc("mfg_r3", exc)
        log_structured("council_runner.manufacturing_r3_stub", error=_ascii_debug(str(exc), 200))
        r3 = "_Tech Integration returned empty._"

    if not r3:
        r3 = "_Tech Integration returned empty._"

    merge_user = f"""Merge the three expert sections below into **one** Markdown document (see SYNTHESIS_MANUFACTURING_EMPIRE for exact H1 and H2 structure).

### Source - Round 1 Manufacturing & Industrial Operations
{clip_prior(r1)}

### Source - Round 2 Financial Engine (Economic Architect)
{clip_prior(r2)}

### Source - Round 3 Tech Integration (Tech Strategist)
{clip_prior(r3)}
"""
    merge_user = merge_user_structured_envelope(merge_user)
    try:
        final = groq_completion_single(
            registry,
            client,
            get_prompt("SYNTHESIS_MANUFACTURING_EMPIRE"),
            merge_user,
            event_suffix="mfg_merge",
        )
    except Exception as exc:
        _council_handle_exc("mfg_merge", exc)
        log_structured("council_runner.manufacturing_synthesis_stub", error=_ascii_debug(str(exc), 200))
        final = ""

    if final and len(final) > 200:
        return final
    return (
        "THIRAMAI 2026 STRATEGY ANALYSIS\n\n"
        "# THIRAMAI TECH EMPIRE: SOVEREIGN STRATEGY BRIEF\n\n"
        + r1
        + "\n\n---\n\n"
        + r2
        + "\n\n---\n\n"
        + r3
    )


def run_vault_personal_council(registry: ToolRegistry, client: Groq, shared_core: str) -> str:
    r1_user = f"""{shared_core}

## Council Round 1 - Personal Health & Sovereign Rhythm
"""
    try:
        r1 = groq_completion_single(
            registry,
            client,
            get_prompt("PROMPT_VAULT_PERSONAL_R1"),
            r1_user,
            event_suffix="pv_r1",
        )
    except Exception as exc:
        _council_handle_exc("pv_r1", exc)
        log_structured("council_runner.personal_vault_r1_stub", error=_ascii_debug(str(exc), 200))
        r1 = "_Personal Health round unavailable._"

    if not r1:
        r1 = "_Personal Health round empty._"

    r2_user = f"""{shared_core}

## Prior - Round 1
{clip_prior(r1)}

## Council Round 2 - Vault Business & Priorities
"""
    try:
        r2 = groq_completion_single(
            registry,
            client,
            get_prompt("PROMPT_VAULT_PERSONAL_R2"),
            r2_user,
            event_suffix="pv_r2",
        )
    except Exception as exc:
        _council_handle_exc("pv_r2", exc)
        log_structured("council_runner.personal_vault_r2_stub", error=_ascii_debug(str(exc), 200))
        r2 = "_Vault Business round unavailable._"

    if not r2:
        r2 = "_Vault Business round empty._"

    r3_user = f"""{shared_core}

## Round 1
{clip_prior(r1)}

## Round 2
{clip_prior(r2)}

## Council Round 3 - Systems, Habits & Light Tech
"""
    try:
        r3 = groq_completion_single(
            registry,
            client,
            get_prompt("PROMPT_VAULT_PERSONAL_R3"),
            r3_user,
            event_suffix="pv_r3",
        )
    except Exception as exc:
        _council_handle_exc("pv_r3", exc)
        log_structured("council_runner.personal_vault_r3_stub", error=_ascii_debug(str(exc), 200))
        r3 = "_Systems round unavailable._"

    if not r3:
        r3 = "_Systems round empty._"

    merge_user = f"""Merge into one Markdown report per SYNTHESIS_PERSONAL_VAULT.

### R1
{clip_prior(r1)}
### R2
{clip_prior(r2)}
### R3
{clip_prior(r3)}
"""
    merge_user = merge_user_structured_envelope(merge_user)
    try:
        final = groq_completion_single(
            registry,
            client,
            get_prompt("SYNTHESIS_PERSONAL_VAULT"),
            merge_user,
            event_suffix="pv_merge",
        )
    except Exception as exc:
        _council_handle_exc("pv_merge", exc)
        log_structured("council_runner.personal_vault_synthesis_stub", error=_ascii_debug(str(exc), 200))
        final = ""

    if final and len(final) > 200:
        return final
    return (
        "THIRAMAI 2026 STRATEGY ANALYSIS\n\n"
        "# THIRAMAI TECH EMPIRE: SOVEREIGN STRATEGY BRIEF\n\n"
        + r1
        + "\n\n---\n\n"
        + r2
        + "\n\n---\n\n"
        + r3
    )


def run_industrial_dpr_loop(
    registry: ToolRegistry, client: Groq, shared_core: str
) -> tuple[str, str]:
    system_base = get_prompt("SYSTEM_PROMPT_INDUSTRIAL_DPR")
    anti = get_prompt("ANTI_REPEAT")
    system_content = f"{system_base}\n\n{anti}"
    round1_user, round2_user, round3_user = round_prompts_industrial_dpr(shared_core)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": round1_user},
    ]
    chunks: list[str] = []
    round_prompts = [round1_user, round2_user, round3_user]
    for i, prompt in enumerate(round_prompts):
        if i > 0:
            messages.append({"role": "user", "content": prompt})
        try:
            completion = registry.groq_chat_completions_create(
                client,
                messages=messages,
                event_label=f"groq.dpr_r{i + 1}",
            )
        except Exception as exc:
            if looks_like_length_limit_error(exc):
                raise QueryLengthExceeded(
                    "The model request was too long for the provider. "
                    "Try a shorter brief (under 5000 characters) or narrow the topic."
                ) from exc
            log_structured(
                "council_runner.industrial_dpr_round_failed",
                round=i + 1,
                error=_ascii_debug(str(exc), 200),
            )
            break
        choice = completion.choices[0].message.content
        if not choice or not choice.strip():
            break
        piece = choice.strip()
        chunks.append(piece)
        messages.append({"role": "assistant", "content": piece})
    final = "\n\n---\n\n".join(chunks)
    return final, system_content
