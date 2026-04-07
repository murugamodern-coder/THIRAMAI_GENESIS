#!/usr/bin/env python3
"""
Legacy entrypoint — use **migrate_vault.py** for THIRAMAI V2.1 (dedup + hollow block + seed).
"""

from migrate_vault import main

if __name__ == "__main__":
    raise SystemExit(main())
