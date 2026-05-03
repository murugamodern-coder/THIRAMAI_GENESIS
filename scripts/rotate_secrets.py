#!/usr/bin/env python3
"""Rotate application secrets via :mod:`core.secrets_manager`.

Usage:
  python scripts/rotate_secrets.py --secret SECRET_KEY
  python scripts/rotate_secrets.py --all --dry-run

Grace period (blocking sleep) after writing is optional; keep it in this script, not in request paths.
"""

from __future__ import annotations

import argparse
import logging
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.secrets_manager import get_secrets_manager  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def generate_secret(secret_name: str) -> str:
    u = secret_name.upper()
    if any(x in u for x in ("PASSWORD", "PASS")):
        return secrets.token_urlsafe(32)
    return secrets.token_hex(32)


def rotate_secret(secret_name: str, *, dry_run: bool = False, grace_seconds: int = 0) -> bool:
    logger.info("Rotating secret key=%s dry_run=%s", secret_name, dry_run)
    new_value = generate_secret(secret_name)

    if dry_run:
        logger.info("[DRY RUN] would set key=%s prefix=%s...", secret_name, new_value[:8])
        return True

    mgr = get_secrets_manager()
    ok = mgr.rotate(secret_name, new_value, grace_period_seconds=0)
    if ok and grace_seconds > 0:
        logger.info("Post-rotate grace sleep seconds=%s (in-flight requests)", grace_seconds)
        time.sleep(float(grace_seconds))
        mgr.clear_cache()

    if ok:
        logger.info("Successfully rotated key=%s", secret_name)
    else:
        logger.error("Failed to rotate key=%s", secret_name)
    return ok


def rotate_all_secrets(*, dry_run: bool = False, grace_seconds: int = 0) -> bool:
    rotatable = [
        "SECRET_KEY",
        "JWT_SECRET_KEY",
        "JWT_SECRET",
    ]
    manual = [
        "DATABASE_URL",
        "KITE_API_KEY",
        "KITE_ACCESS_TOKEN",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GROQ_API_KEY",
    ]
    logger.info(
        "Rotating %d keys; skipping manual/provider keys: %s",
        len(rotatable),
        ", ".join(manual),
    )
    results = [rotate_secret(k, dry_run=dry_run) for k in rotatable]
    ok_all = all(results)
    if ok_all and grace_seconds > 0 and not dry_run:
        logger.info("Post-batch grace sleep seconds=%s", grace_seconds)
        time.sleep(float(grace_seconds))
        get_secrets_manager().clear_cache()
    return ok_all


def main() -> None:
    p = argparse.ArgumentParser(description="Rotate application secrets")
    p.add_argument("--secret", help="Specific secret name to rotate")
    p.add_argument("--all", action="store_true", help="Rotate all auto-rotatable secrets")
    p.add_argument("--dry-run", action="store_true", help="Do not write")
    p.add_argument(
        "--grace-seconds",
        type=int,
        default=0,
        help="Optional blocking sleep after each successful rotate (worker/job use only)",
    )
    args = p.parse_args()

    if not args.secret and not args.all:
        p.error("Specify --secret NAME or --all")

    ok = rotate_all_secrets(dry_run=args.dry_run, grace_seconds=args.grace_seconds) if args.all else rotate_secret(
        args.secret, dry_run=args.dry_run, grace_seconds=args.grace_seconds
    )
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
