"""
Load ``.env`` from the project root and report missing expected keys (no secret values).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Keys we expect in a typical local ``.env`` (names only; values never printed).
EXPECTED_ENV_KEYS: tuple[str, ...] = (
    "DATABASE_URL",
    "SECRET_KEY",
    "JWT_SECRET",
    "GROQ_API_KEY",
    "TAVILY_API_KEY",
)


def load_project_dotenv(*, root: Path | None = None, override: bool = True) -> tuple[Path, bool]:
    """
    Load ``<root>/.env`` via python-dotenv. Returns ``(path, file_existed)``.
    """
    r = root or PROJECT_ROOT
    env_path = r / ".env"
    existed = env_path.is_file()
    load_dotenv(dotenv_path=env_path, override=override)
    return env_path, existed


def missing_expected_keys(keys: Iterable[str] | None = None) -> list[str]:
    """Return names of expected keys that are unset or empty after load."""
    want = tuple(keys) if keys is not None else EXPECTED_ENV_KEYS
    missing: list[str] = []
    for k in want:
        v = os.getenv(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            missing.append(k)
    return missing


def report_env_status(*, keys: Iterable[str] | None = None, print_fn=print) -> list[str]:
    """
    Print human-readable status for ``.env`` and missing keys. Returns the missing key list.
    """
    env_path, existed = load_project_dotenv()
    missing = missing_expected_keys(keys)
    if not existed:
        print_fn(f"[env] No .env file at {env_path} (create it or set variables in the environment).")
    else:
        print_fn(f"[env] Loaded .env from {env_path}")
    if missing:
        print_fn(f"[env] Missing or empty expected keys: {', '.join(missing)}")
    else:
        print_fn("[env] All expected keys are set (values not shown).")
    return missing
