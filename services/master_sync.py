"""
Master database + tenant repair entry point (same pipeline as ``python -m services.verify_keys --sync``).

Run from repo root with ``DATABASE_URL`` set::

    python -m services.master_sync
    python -m services.master_sync --org-id 3 --profile development
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from core.database import diagnose_postgresql_url
from core.env_bootstrap import report_env_status
from services.verify_keys import run_master_database_sync


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Alembic + Modern Corporation org repair + heartbeat + SRE + thought log.")
    p.add_argument("--org-id", type=int, default=3, help="Organization id for Modern Corporation (default: 3)")
    p.add_argument("--profile", default="development", choices=("development", "production"))
    p.add_argument("--no-heartbeat", action="store_true", help="Skip external API heartbeat")
    p.add_argument("--no-sre", action="store_true", help="Skip SRE snapshot")
    p.add_argument("--no-thought", action="store_true", help="Skip thought_stream.json append")
    p.add_argument("--json", action="store_true", help="Print full result JSON to stdout")
    args = p.parse_args(argv)

    print("Step 0: Loading .env from project root and checking expected keys...", flush=True)
    report_env_status()

    probe_url = (os.getenv("DATABASE_URL") or "").strip()
    print(
        "Step 0b: Testing PostgreSQL connectivity for DATABASE_URL "
        "(e.g. postgresql://postgres:***@localhost:5432/thiramai_db - password not printed)...",
        flush=True,
    )
    if not probe_url:
        print(
            "  Skipped: DATABASE_URL is unset. Set it in .env at the project root to match your Postgres instance.",
            flush=True,
        )
    else:
        diag = diagnose_postgresql_url(probe_url)
        tgt = diag.get("target") or {}
        host = tgt.get("host", "?")
        port = tgt.get("port", "?")
        dbn = tgt.get("database", "?")
        user = tgt.get("user", "?")
        print(f"  Target: host={host} port={port} db={dbn} user={user}", flush=True)
        if diag.get("ok"):
            print("  Result: OK - database accepted the connection.", flush=True)
        else:
            cat = diag.get("category") or "other"
            print(f"  Result: FAILED - {diag.get('detail', '')}", flush=True)
            if cat == "authentication_failed":
                print(
                    "  Classification: authentication / password issue (not a server-down refusal).",
                    flush=True,
                )
            elif cat == "server_unreachable":
                print(
                    "  Classification: server unreachable or not listening (not a password success path).",
                    flush=True,
                )
            else:
                print("  Classification: other / see detail above.", flush=True)

    out = run_master_database_sync(
        profile=args.profile,
        modern_corporation_org_id=int(args.org_id),
        run_heartbeat=not args.no_heartbeat,
        run_sre_snapshot=not args.no_sre,
        log_thought_stream=not args.no_thought,
        heartbeat_log_groq=True,
        verbose=True,
    )
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
