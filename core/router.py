"""Intent routing: Industrial (Financial DPR) vs Manufacturing vault vs Personal vs Sovereign/Agri default."""

from __future__ import annotations

from enum import Enum

import vault_memory

from core.policies.loader import get_config


class RouteMode(str, Enum):
    INDUSTRIAL_DPR = "industrial_dpr"
    MANUFACTURING_EMPIRE = "manufacturing_empire"
    PERSONAL_VAULT = "personal_vault"
    AGRI_DEFAULT = "agri_default"


def _norm(s: str) -> str:
    return (s or "").lower().replace("\u2019", "'")


def _routing_cfg() -> dict:
    r = (get_config().get("routing") or {})
    return r if isinstance(r, dict) else {}


def query_is_personal_vault_priority(user_message: str) -> bool:
    u = _norm(user_message)
    subs = _routing_cfg().get("personal_vault_substrings") or ()
    return any(sub in u for sub in subs)


def query_is_next_rd_step(user_message: str) -> bool:
    u = _norm(user_message)
    subs = _routing_cfg().get("next_rd_step_substrings") or ()
    if any(s in u for s in subs):
        return True
    return "next" in u and "research" in u and "step" in u


def query_is_robot_learning(user_message: str) -> bool:
    u = _norm(user_message)
    subs = _routing_cfg().get("robot_learning_substrings") or ()
    if any(s in u for s in subs):
        return True
    return "robot" in u and "learn" in u


def query_is_build_robot_now(user_message: str) -> bool:
    u = _norm(user_message)
    subs = _routing_cfg().get("build_robot_substrings") or ()
    if any(s in u for s in subs):
        return True
    return ("build" in u and "robot" in u) and ("now" in u or "can we" in u or "can i" in u)


def route_is_industrial_business(user_message: str) -> bool:
    low = _norm(user_message)
    kws = frozenset(_routing_cfg().get("industrial_route_keywords") or [])
    return any(kw in low for kw in kws)


def resolve_route_mode(user_message: str) -> tuple[RouteMode, str]:
    industrial = route_is_industrial_business(user_message)
    has_business_vault = vault_memory.business_current_loaded()
    personal_vault = query_is_personal_vault_priority(user_message)

    if industrial:
        return RouteMode.INDUSTRIAL_DPR, "Industrial Business DPR"
    if has_business_vault:
        return RouteMode.MANUFACTURING_EMPIRE, "Manufacturing Empire Council (vault business_current)"
    if personal_vault:
        return RouteMode.PERSONAL_VAULT, "Personal Vault Council (no agri default)"
    return RouteMode.AGRI_DEFAULT, "THIRAMAI Tech Empire (Agri-default 3-Agent Council)"
