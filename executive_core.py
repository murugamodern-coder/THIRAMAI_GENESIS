"""
Executive Personal Assistant (EPA): agenda, health snapshot, daily_log, task categories.
Persistent JSON under vault/; daily_log.txt for human-readable progress.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
VAULT_DIR = ROOT / "vault"
AGENDA_PATH = VAULT_DIR / "agenda_state.json"
PROFILE_PATH = VAULT_DIR / "user_profile.json"
DAILY_LOG_PATH = VAULT_DIR / "daily_log.txt"

_DEFAULT_PROFILE: dict[str, Any] = {
    "daily_sleep_goal_hours": 8,
    "water_intake_goal_glasses": 8,
    "water_intake_goal_liters_per_day": None,
    "key_meetings": [],
    "current_business_blockers": [],
    "last_morning_brief_date": "",
}

TASK_CATEGORIES = (
    "Personal Health",
    "Manufacturing Operations",
    "Empire R&D",
)

_STRESS_MARKERS = (
    "stress",
    "stressed",
    "exhausted",
    "burnout",
    "can't sleep",
    "cant sleep",
    "no sleep",
    "overwork",
    "overwhelmed",
    "anxious",
    "2am",
    "3am",
    "4am",
    "late night",
)

_LATE_WORK_MARKERS = ("2am", "3am", "4am", "5am", "midnight", "late night", "still working", "pulling an all-nighter")


def ensure_vault() -> None:
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    if not DAILY_LOG_PATH.is_file():
        DAILY_LOG_PATH.write_text(
            "# THIRAMAI Empire - Daily progress & health log (UTF-8)\n\n",
            encoding="utf-8",
        )
    if not AGENDA_PATH.is_file():
        AGENDA_PATH.write_text(
            json.dumps(
                {
                    "health_today": {
                        "sleep_hours": None,
                        "water_glasses": None,
                        "stress_1_10": None,
                        "last_updated": "",
                    },
                    "meetings": [],
                    "tasks": [],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    if not PROFILE_PATH.is_file():
        PROFILE_PATH.write_text(
            json.dumps(_DEFAULT_PROFILE, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def load_user_profile() -> dict[str, Any]:
    ensure_vault()
    try:
        data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return dict(_DEFAULT_PROFILE)
        out = dict(_DEFAULT_PROFILE)
        out.update(data)
        return out
    except (json.JSONDecodeError, OSError):
        return dict(_DEFAULT_PROFILE)


def save_user_profile(data: dict[str, Any]) -> None:
    ensure_vault()
    PROFILE_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def format_user_profile_block() -> str:
    p = load_user_profile()
    km = p.get("key_meetings") or []
    bl = p.get("current_business_blockers") or []
    liters = p.get("water_intake_goal_liters_per_day")
    water_line = f"- **Water goal**: {p.get('water_intake_goal_glasses', 'n/a')} glasses (target)"
    if liters is not None:
        water_line += f"; **{liters} L/day** target from profile"
    lines = [
        "### User profile (goals & blockers)",
        f"- **Sleep goal**: {p.get('daily_sleep_goal_hours', 'n/a')} h/night",
        water_line,
        "- **Key meetings** (pinned):",
    ]
    if km:
        for m in km[:12]:
            lines.append(f"  - {m}")
    else:
        lines.append("  - (none in profile; add to user_profile.json)")
    lines.append("- **Current business blockers**:")
    if bl:
        for b in bl[:12]:
            lines.append(f"  - {b}")
    else:
        lines.append("  - (none listed)")
    return "\n".join(lines)


def is_local_late_night(hour_threshold: int = 22) -> bool:
    """True if local wall-clock hour is >= threshold (10 PM)."""
    return datetime.now().hour >= hour_threshold


def morning_brief_pending_today() -> tuple[bool, str]:
    """(should_show_brief, today_iso local)."""
    today = datetime.now().date().isoformat()
    p = load_user_profile()
    last = (p.get("last_morning_brief_date") or "").strip()
    return (last != today, today)


def mark_morning_brief_shown(today_iso: str) -> None:
    p = load_user_profile()
    p["last_morning_brief_date"] = today_iso
    save_user_profile(p)


def _top_business_tasks_from_state(limit: int = 3) -> list[str]:
    data = load_agenda_state()
    tasks = [t for t in (data.get("tasks") or []) if not t.get("done")]
    out = [f"[{t.get('category', '')}] {t.get('title', '')}" for t in tasks[:limit]]
    if len(out) >= limit:
        return out
    # Supplement from daily_log TASK lines
    tail = _tail_daily_log(25).splitlines()
    for ln in reversed(tail):
        if "TASK " in ln or "TASK [" in ln:
            out.append(ln.strip()[:200])
            if len(out) >= limit:
                break
    return out[:limit]


def _strategic_insight_paragraph() -> str:
    """Opening narrative: growth engine (ops + R&D), not task dump."""
    return (
        "Your **Empire Vision** for **2026** stacks **pipe-grade sovereignty** (HDPE/PVC extrusion, invoice-grade ops) as the **cash and materials base**, "
        "**solar–agri integration** as **energy and margin diversification**, and **humanoid robotics R&D** where the **same polymer discipline** feeds **prototypes** "
        "(frames, guards, ducts — see `vault/rd_core/`). The Sovereign loop: **restart the line**, protect **GST rhythm**, and **fund R&D** without fragmenting focus."
    )


def _procurement_advice_block() -> str:
    try:
        from factory import market_watch

        return str(market_watch.procurement_advice_markdown()).strip()
    except Exception:
        return (
            "_Procurement tape unavailable (`factory/market_watch.py`). "
            "Check HDPE/LLDPE offers manually with your distributor._"
        )


def _next_research_task_block() -> str:
    try:
        import vault_memory

        return str(vault_memory.next_research_task_for_brief()).strip()
    except Exception:
        return "_Next research task helper unavailable._"


def build_sovereign_morning_brief() -> str:
    """Mandatory first-run-of-day block (prepended to model output)."""
    p = load_user_profile()
    h = load_agenda_state().get("health_today") or {}
    today = datetime.now().date().isoformat()
    dl = parse_daily_log_health_signals(for_date_iso=today)
    sleep_g = p.get("daily_sleep_goal_hours", 8)
    water_g = p.get("water_intake_goal_glasses", 8)
    liters_goal = p.get("water_intake_goal_liters_per_day")
    liters_hint = f" | profile **{liters_goal} L/day**" if liters_goal is not None else ""

    sleep_val = h.get("sleep_hours")
    sleep_tag = "agenda_state"
    if sleep_val is None and dl.get("sleep_hours") is not None:
        sleep_val = dl.get("sleep_hours")
        sleep_tag = "daily_log (HEALTH)"
    if sleep_val is not None:
        sleep_line = f"- Logged sleep: **{sleep_val}** h (goal {sleep_g} h) — _source: {sleep_tag}_"
    elif dl.get("health_note"):
        note = (dl["health_note"] or "")[:200]
        if len(dl.get("health_note") or "") > 200:
            note += "..."
        sleep_line = f"- Logged sleep: **{note}** (goal {sleep_g} h) — _daily_log `HEALTH:` line_"
    else:
        sleep_line = f"- Logged sleep: **not logged** (goal {sleep_g} h)"

    water_val = h.get("water_glasses")
    water_tag = "agenda_state"
    if water_val is None and dl.get("water_glasses") is not None:
        water_val = dl.get("water_glasses")
        water_tag = "daily_log (HEALTH)"
    if water_val is not None:
        water_line = (
            f"- Logged water: **{water_val}** glasses (goal {water_g}){liters_hint} — _source: {water_tag}_"
        )
    elif dl.get("water_note"):
        water_line = (
            f"- Logged water: **{dl['water_note']}** (glasses goal {water_g}){liters_hint} — _daily_log HEALTH_"
        )
    else:
        water_line = f"- Logged water: **not logged** (glasses goal {water_g}){liters_hint}"

    stress = h.get("stress_1_10")
    health_lines = [
        sleep_line,
        water_line,
        (
            f"- Stress (1-10): **{stress}/10**"
            if stress is not None
            else "- Stress (1-10): **not logged**"
        ),
    ]
    top3 = _top_business_tasks_from_state(3)
    agenda_lines = [f"{i + 1}. {t}" for i, t in enumerate(top3)] if top3 else ["1. (No tasks in agenda yet - add via [EPA task ...|Category])"]
    return (
        "## Sovereign Morning Brief\n\n"
        "Sovereign Leader, welcome back.\n\n"
        "### Strategic Insight\n\n"
        + _strategic_insight_paragraph()
        + "\n\n### Procurement Advice\n\n"
        + _procurement_advice_block()
        + "\n\n### Next Research Task\n\n"
        + _next_research_task_block()
        + "\n\n### Health status\n"
        + "\n".join(health_lines)
        + "\n\n### Agenda (top business tasks)\n"
        + "\n".join(agenda_lines)
        + "\n\n---\n"
    )


def load_agenda_state() -> dict[str, Any]:
    ensure_vault()
    try:
        return json.loads(AGENDA_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {
            "health_today": {
                "sleep_hours": None,
                "water_glasses": None,
                "stress_1_10": None,
                "last_updated": "",
            },
            "meetings": [],
            "tasks": [],
        }


def save_agenda_state(data: dict[str, Any]) -> None:
    ensure_vault()
    AGENDA_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def append_daily_log(line: str) -> None:
    ensure_vault()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    safe = (line or "").strip().replace("\r\n", " ").replace("\n", " ")
    with DAILY_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"{ts} | {safe}\n")


def record_health(sleep_hours: float | None, water_glasses: int | None, stress_1_10: int | None) -> None:
    """Programmatic health update (EPA)."""
    data = load_agenda_state()
    h = data.setdefault("health_today", {})
    if sleep_hours is not None:
        h["sleep_hours"] = sleep_hours
    if water_glasses is not None:
        h["water_glasses"] = water_glasses
    if stress_1_10 is not None:
        h["stress_1_10"] = max(1, min(10, stress_1_10))
    h["last_updated"] = datetime.now(timezone.utc).isoformat()
    save_agenda_state(data)
    parts = []
    if sleep_hours is not None:
        parts.append(f"sleep={sleep_hours}h")
    if water_glasses is not None:
        parts.append(f"water={water_glasses} glasses")
    if stress_1_10 is not None:
        parts.append(f"stress={stress_1_10}/10")
    if parts:
        append_daily_log("HEALTH " + " | ".join(parts))


def add_meeting(title: str, when_iso: str, notes: str = "") -> None:
    data = load_agenda_state()
    mid = 1 + max((m.get("id", 0) for m in data.get("meetings", [])), default=0)
    data.setdefault("meetings", []).append(
        {"id": mid, "title": title.strip(), "when_iso": when_iso.strip(), "notes": notes.strip()}
    )
    save_agenda_state(data)
    append_daily_log(f"MEETING added: {title} @ {when_iso}")


def add_task(title: str, category: str) -> None:
    if category not in TASK_CATEGORIES:
        category = "Empire R&D"
    data = load_agenda_state()
    tid = 1 + max((t.get("id", 0) for t in data.get("tasks", [])), default=0)
    data.setdefault("tasks", []).append(
        {"id": tid, "title": title.strip(), "category": category, "done": False}
    )
    save_agenda_state(data)
    append_daily_log(f"TASK [{category}]: {title}")


def _tail_daily_log(max_lines: int = 12) -> str:
    if not DAILY_LOG_PATH.is_file():
        return "(daily_log empty)"
    try:
        lines = DAILY_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "(daily_log unreadable)"
    tail = [ln for ln in lines if ln.strip() and not ln.strip().startswith("#")][-max_lines:]
    return "\n".join(tail) if tail else "(no entries yet)"


def heuristic_health_signals(user_text: str) -> tuple[bool, bool]:
    """Returns (stress_like, late_work_like)."""
    low = (user_text or "").lower()
    stress = any(m in low for m in _STRESS_MARKERS)
    late = any(m in low for m in _LATE_WORK_MARKERS)
    return stress, late


_EPA_HEALTH = re.compile(
    r"\[EPA\s+health\s+([^\]]+)\]",
    re.IGNORECASE,
)
_EPA_MEET = re.compile(
    r"\[EPA\s+meeting\s+([^\|]+)\|\s*([^\]]+)\]",
    re.IGNORECASE,
)
_EPA_TASK = re.compile(
    r"\[EPA\s+task\s+([^\|]+)\|\s*([^\]]+)\]",
    re.IGNORECASE,
)

# daily_log.txt: dated blocks like [2026-03-30] and lines HEALTH: ...
_DATE_BLOCK_HEADER = re.compile(r"^\[(\d{4}-\d{2}-\d{2})\]\s*$")
_HEALTH_PREFIX = re.compile(r"^HEALTH:\s*(.+)$", re.IGNORECASE)
# "Slept only 6 hours", "sleep 6h", "6 hours yesterday"
_SLEEP_HOURS_IN_TEXT = re.compile(
    r"(?:slept|sleep)\s+(?:only\s+)?(\d+(?:\.\d+)?)\s*h(?:ours?)?|(\d+(?:\.\d+)?)\s*hours?\b",
    re.IGNORECASE,
)
_WATER_IN_HEALTH = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:L|l|liters?|litres?|glasses?)\b",
    re.IGNORECASE,
)
_LOG_PIPE_HEALTH = re.compile(
    r"HEALTH\s+(.+)$",
    re.IGNORECASE,
)


def _split_daily_log_into_date_blocks(text: str) -> list[tuple[str | None, list[str]]]:
    """Return [(date_iso_or_none, lines_in_block), ...] in file order."""
    blocks: list[tuple[str | None, list[str]]] = []
    current_date: str | None = None
    current_lines: list[str] = []
    for line in text.splitlines():
        m = _DATE_BLOCK_HEADER.match(line.strip())
        if m:
            if current_lines or current_date is not None:
                blocks.append((current_date, current_lines))
            current_date = m.group(1)
            current_lines = []
            continue
        current_lines.append(line)
    if current_lines or current_date is not None:
        blocks.append((current_date, current_lines))
    if not blocks and text.strip():
        blocks.append((None, text.splitlines()))
    return blocks


def parse_daily_log_health_signals(for_date_iso: str | None = None) -> dict[str, Any]:
    """
    Read vault/daily_log.txt for HEALTH: lines and structured HEALTH tails from append_daily_log.
    Merges with agenda_state when morning brief is built (JSON wins when set).
    """
    for_date_iso = for_date_iso or datetime.now().date().isoformat()
    out: dict[str, Any] = {
        "sleep_hours": None,
        "water_glasses": None,
        "water_note": None,
        "health_note": None,
        "block_date": None,
        "source": None,
    }
    if not DAILY_LOG_PATH.is_file():
        return out
    try:
        raw = DAILY_LOG_PATH.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out

    blocks = _split_daily_log_into_date_blocks(raw)
    chosen: tuple[str | None, list[str]] | None = None
    for d, lines in reversed(blocks):
        if d == for_date_iso:
            chosen = (d, lines)
            break
    if chosen is None and blocks:
        # Prefer last dated block, else last block
        for d, lines in reversed(blocks):
            if d is not None:
                chosen = (d, lines)
                break
        if chosen is None:
            chosen = blocks[-1]

    if not chosen:
        return out

    block_date, lines = chosen
    out["block_date"] = block_date
    health_texts: list[str] = []

    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        hm = _HEALTH_PREFIX.match(s)
        if hm:
            health_texts.append(hm.group(1).strip())
            continue
        if "|" in s and "HEALTH" in s.upper():
            pm = _LOG_PIPE_HEALTH.search(s)
            if pm:
                health_texts.append(pm.group(1).strip())

    for ln in reversed(lines):
        s = ln.strip()
        if "|" in s and "HEALTH" in s.upper():
            # sleep=7 water=8 from record_health append
            sh = re.search(r"sleep\s*=\s*([\d.]+)h?", s, re.I)
            wg = re.search(r"water\s*=\s*(\d+)", s, re.I)
            if sh and out["sleep_hours"] is None:
                try:
                    out["sleep_hours"] = float(sh.group(1))
                    out["source"] = "daily_log_structured"
                except ValueError:
                    pass
            if wg and out["water_glasses"] is None:
                try:
                    out["water_glasses"] = int(wg.group(1))
                    if not out["source"]:
                        out["source"] = "daily_log_structured"
                except ValueError:
                    pass

    if health_texts:
        blob = " ".join(health_texts)
        out["health_note"] = blob[:500]
        if out["sleep_hours"] is None:
            sm = _SLEEP_HOURS_IN_TEXT.search(blob)
            if sm:
                g = sm.group(1) or sm.group(2)
                if g:
                    try:
                        out["sleep_hours"] = float(g)
                        out["source"] = out["source"] or "daily_log_HEALTH_line"
                    except ValueError:
                        pass
        if out.get("water_note") is None and out["water_glasses"] is None:
            wm = _WATER_IN_HEALTH.search(blob)
            if wm:
                span = wm.group(0).lower()
                try:
                    val = float(wm.group(1))
                except ValueError:
                    val = None
                if val is not None:
                    if "glass" in span:
                        out["water_glasses"] = int(val)
                        out["source"] = out["source"] or "daily_log_HEALTH_line"
                    else:
                        out["water_note"] = f"{wm.group(1)} L (from daily_log HEALTH line)"

    return out


def ingest_epa_tags(user_message: str) -> None:
    """Parse optional [EPA ...] tags from user message and update state."""
    if not user_message or "[EPA" not in user_message:
        return
    for m in _EPA_HEALTH.finditer(user_message):
        chunk = m.group(1)
        sh = re.search(r"sleep\s*=\s*([\d.]+)", chunk, re.I)
        wg = re.search(r"water\s*=\s*(\d+)", chunk, re.I)
        st = re.search(r"stress\s*=\s*(\d+)", chunk, re.I)
        record_health(
            float(sh.group(1)) if sh else None,
            int(wg.group(1)) if wg else None,
            int(st.group(1)) if st else None,
        )
    for m in _EPA_MEET.finditer(user_message):
        add_meeting(m.group(2).strip(), m.group(1).strip())
    for m in _EPA_TASK.finditer(user_message):
        cat = m.group(2).strip()
        if cat not in TASK_CATEGORIES:
            cat = "Empire R&D"
        add_task(m.group(1).strip(), cat)


def format_empire_agenda_block() -> str:
    """Static summary for prompts (no LLM)."""
    data = load_agenda_state()
    h = data.get("health_today") or {}
    today = datetime.now().date().isoformat()
    dlh = parse_daily_log_health_signals(for_date_iso=today)
    dl_sleep = dlh.get("sleep_hours")
    dl_note = (dlh.get("health_note") or "")[:120]
    if dl_note and len(dlh.get("health_note") or "") > 120:
        dl_note += "..."
    log_health_hint = ""
    if h.get("sleep_hours") is None and (dl_sleep is not None or dl_note):
        log_health_hint = (
            f" | _daily_log:_ sleep_parse={dl_sleep if dl_sleep is not None else 'n/a'}"
            + (f", note={dl_note!r}" if dl_note else "")
        )
    lines = [
        "### Empire Agenda (persisted)",
        f"- **Health today**: sleep={h.get('sleep_hours', 'n/a')}h, "
        f"water_glasses={h.get('water_glasses', 'n/a')}, "
        f"stress={h.get('stress_1_10', 'n/a')}/10 (last update: {h.get('last_updated') or 'n/a'})"
        f"{log_health_hint}",
    ]
    meetings = data.get("meetings") or []
    if meetings:
        lines.append("- **Meetings**:")
        for m in meetings[-8:]:
            lines.append(f"  - [{m.get('when_iso', '')}] {m.get('title', '')}")
    else:
        lines.append("- **Meetings**: (none stored)")
    tasks = [t for t in (data.get("tasks") or []) if not t.get("done")]
    if tasks:
        lines.append("- **Open tasks** (categorize as Personal Health / Manufacturing Operations / Empire R&D):")
        for t in tasks[-12:]:
            lines.append(f"  - [{t.get('category', '')}] {t.get('title', '')}")
    else:
        lines.append("- **Open tasks**: (none stored)")
    lines.append("\n### Recent daily_log (tail)")
    lines.append(_tail_daily_log(10))
    return "\n".join(lines)


def format_health_reminder_block(stress_hint: bool, late_hint: bool) -> str:
    parts = []
    if stress_hint:
        parts.append(
            "HEURISTIC: User text suggests elevated stress - CEO should recommend a short break, breathing, or health check."
        )
    if late_hint:
        parts.append(
            "HEURISTIC: User text suggests late-night work - CEO should suggest winding down, sleep hygiene, or deferring non-critical tasks."
        )
    if not parts:
        parts.append("HEURISTIC: No strong stress/late-work signals in raw text.")
    parts.append(
        "Reminders: target 7-9h sleep, steady hydration, log via [EPA health sleep=7 water=8 stress=4] in any query."
    )
    return "\n".join(parts)
