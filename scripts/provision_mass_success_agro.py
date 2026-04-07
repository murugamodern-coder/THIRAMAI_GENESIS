"""
Provision **Mass Success Agro Agency** (organizations.id = 2): tenant defaults, SKUs, optional user links.

Usage (from repo root, with DATABASE_URL in .env):

    python scripts/provision_mass_success_agro.py
    python scripts/provision_mass_success_agro.py --link-users 1,2

Does not alter **Modern Corporation** (id 3) or other orgs except ensuring id=2 exists as named.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.database import get_session_factory  # noqa: E402
from core.env_bootstrap import load_project_dotenv  # noqa: E402
from services.organization_service import provision_mass_success_agro_agency  # noqa: E402


def main() -> int:
    load_project_dotenv(root=ROOT)
    p = argparse.ArgumentParser(description="Provision Mass Success Agro Agency (org id=2).")
    p.add_argument(
        "--link-users",
        type=str,
        default="",
        help="Comma-separated users.id values to attach as owner of org 2 (optional).",
    )
    args = p.parse_args()
    factory = get_session_factory()
    if factory is None:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 1
    uids: list[int] = []
    if args.link_users.strip():
        for part in args.link_users.split(","):
            part = part.strip()
            if part.isdigit():
                uids.append(int(part))
    with factory() as session:
        with session.begin():
            out = provision_mass_success_agro_agency(session, link_user_ids=uids or None)
    print(out)
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
