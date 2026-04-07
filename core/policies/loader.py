"""Load system_v1.yaml + prompts_v1.md (cached)."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_POLICIES_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def _yaml_raw() -> dict[str, Any]:
    path = _POLICIES_DIR / "system_v1.yaml"
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError("system_v1.yaml must be a mapping")
    return data


@lru_cache(maxsize=1)
def _prompt_sections() -> dict[str, str]:
    cfg = _yaml_raw()
    md_name = cfg.get("prompts_markdown") or "prompts_v1.md"
    path = _POLICIES_DIR / md_name
    text = path.read_text(encoding="utf-8")
    parts = re.split(r"(?m)^## ([A-Z][A-Z0-9_]*)\s*$", text)
    out: dict[str, str] = {}
    it = iter(parts[1:])
    for name in it:
        body = next(it, "")
        out[name.strip()] = body.strip("\n")
    return out


def policy_version() -> str:
    return str(_yaml_raw().get("version", "1"))


def get_prompt(name: str) -> str:
    return _prompt_sections()[name]


def get_config() -> dict[str, Any]:
    return dict(_yaml_raw())


# Import-time limits for app.brain compatibility
_CFG = _yaml_raw()
_limits = _CFG.get("limits") or {}
MAX_USER_MESSAGE_CHARS: int = int(_limits.get("max_user_message_chars", 5000))
TAVILY_API_QUERY_LIMIT: int = int(_limits.get("tavily_api_query_limit", 200))
GROQ_SEARCH_SUMMARIZER_USER_MAX: int = int(_limits.get("groq_search_summarizer_user_max", 4000))
_COUNCIL_PRIOR_CLIP: int = int(_limits.get("council_prior_clip", 6500))
_MAX_TOKENS: int = int(_limits.get("max_tokens", 4096))
_CEO_MAX_TOKENS: int = int(_limits.get("ceo_max_tokens", 768))

_MODEL = _CFG.get("model") or {}
GROQ_MODEL: str = str(_MODEL.get("groq_model", "llama-3.3-70b-versatile"))
_COMPLETION_TEMPERATURE: float = float(_MODEL.get("completion_temperature", 0.35))

_TIMEOUTS = _CFG.get("timeouts_sec") or {}
GROQ_CHAT_TIMEOUT_SEC: float = float(_TIMEOUTS.get("groq_chat", 120))
TAVILY_SEARCH_TIMEOUT_SEC: float = float(_TIMEOUTS.get("tavily_search", 90))
GROQ_SEARCH_SEED_TIMEOUT_SEC: float = float(_TIMEOUTS.get("groq_search_seed", 45))

_TW = _CFG.get("tamil_watch") or {}
_TAMIL_WORDS = tuple(_TW.get("words") or ("முன்னோடி", "பயன்படும்"))
_MAX_WATCH_WORD: int = int(_TW.get("max_per_word", 3))

_VAULT_SAFE = str(
    _CFG.get("vault_safe_mode_ascii")
    or "[VAULT_SAFE_MODE] Knowledge Vault load failed."
)
