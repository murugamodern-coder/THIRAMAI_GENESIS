"""
Plug-and-play registry for ``POST /dashboard/command/execute``.

Handlers register by canonical action name (underscores, lower case). The LLM must emit matching
``action`` values; add new intents by registering here from optional
``services.dashboard_command_plugins``.
"""

from __future__ import annotations

from typing import Any, Callable

HandlerFn = Callable[..., dict[str, Any]]

_handlers: dict[str, HandlerFn] = {}


def register_dashboard_command_handler(action: str, fn: HandlerFn) -> None:
    key = (action or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not key:
        raise ValueError("action must be non-empty")
    _handlers[key] = fn


def get_dashboard_command_handler(action: str) -> HandlerFn | None:
    key = (action or "").strip().lower().replace("-", "_").replace(" ", "_")
    return _handlers.get(key)
