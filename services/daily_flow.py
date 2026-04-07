"""
Smart Daily Flow: merge business + personal signals for the council when the user asks for scheduling help.
"""

from __future__ import annotations

from core.router import query_is_personal_vault_priority


def user_requests_daily_flow(message: str) -> bool:
    t = (message or "").strip().lower()
    if not t:
        return False
    phrases = (
        "daily flow",
        "plan my day",
        "schedule today",
        "life os",
        "my day plan",
        "optimize my schedule",
        "what should i do today",
        "order my tasks today",
        "how is my day",
        "how's my day",
        "hows my day",
    )
    return any(p in t for p in phrases)


def append_life_os_if_relevant(
    raw: str,
    *,
    organization_id: int,
    user_id: int | None,
    vault_passphrase: str | None,
    max_chars: int = 4200,
) -> str:
    """
    Rich markdown for ``build_executive_pack`` when daily-flow or personal-vault-priority is triggered.
    """
    uid = int(user_id or 0)
    if uid <= 0:
        return ""
    if not (user_requests_daily_flow(raw) or query_is_personal_vault_priority(raw)):
        return ""

    from services.life_os_service import format_life_os_snapshot_markdown

    snap = format_life_os_snapshot_markdown(
        user_id=uid,
        organization_id=int(organization_id),
        vault_passphrase=(vault_passphrase or "").strip() or None,
        max_chars=max_chars,
    )
    directive = ""
    if user_requests_daily_flow(raw):
        directive = (
            "\n\n### Smart Daily Flow (AI directive)\n"
            "Produce a single **Daily Flow** for today: merge **business** work (inventory, pending stock "
            "orders / HITL, operational blockers) with **personal** items (meetings, reminders, health goals). "
            "Use **time blocks** where sensible; keep under **12** bullets; end with one **top priority**.\n"
        )
    return snap + directive
