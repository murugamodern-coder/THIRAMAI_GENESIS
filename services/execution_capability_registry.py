"""
Execution capability registry:
- browser automation (primary)
- API connector fallback
- manual assist fallback
"""

from __future__ import annotations

from typing import Any

from services.browser_automation_controller import BrowserAutomationController


def _browser_available() -> bool:
    try:
        with BrowserAutomationController() as b:
            return bool(b.available())
    except Exception:
        return False


def _api_available() -> bool:
    # API plugin exists in-process; connectivity is handled at runtime per endpoint.
    return True


def _manual_assist_available() -> bool:
    # Manual assist uses in-app notification / summary guidance.
    return True


def get_execution_capabilities(
    *,
    user_id: int,
    organization_id: int,
    command: str = "",
) -> dict[str, Any]:
    _ = (int(user_id), int(organization_id), str(command or ""))
    browser = _browser_available()
    api = _api_available()
    manual = _manual_assist_available()
    primary = "browser_automation" if browser else ("api_fallback" if api else "manual_assist")
    return {
        "ok": True,
        "primary_connector": primary,
        "capabilities": {
            "browser_automation": {"available": browser, "priority": 1},
            "api_fallback": {"available": api, "priority": 2},
            "manual_assist": {"available": manual, "priority": 3},
        },
        "notes": {
            "browser_automation": "Primary for web workflows when Playwright is available.",
            "api_fallback": "Fallback for URL/API-capable commands.",
            "manual_assist": "Last-resort guided/manual path via notifications and summaries.",
        },
    }
