#!/usr/bin/env python3
"""
THIRAMAI V2.1 — transactional vault migration (CSV + JSON) into PostgreSQL.

Sources:
  - factory_output/master_index.csv
  - vault/sales_history.csv (if present) else vault/sales_history.json
  - vault/**/*.json (invoice-shaped lists, optional migration_seed.json)
  - Optional vault/migration_seed.json for organizations, debts, assets, inventory, hollow_block_logs

Dedup: uses external_ref / (organization_id, sku, location) — skips rows already present.

Requires DATABASE_URL.

Usage:
  python migrate_vault.py [--dry-run] [--org-name NAME] [--gst-number GST] [--seed PATH]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.database import get_database_url, get_engine, normalize_database_url  # noqa: E402
from core.db.base import Base  # noqa: E402
from core.db.models import (  # noqa: E402
    Asset,
    AssetStatusEnum,
    Debt,
    DebtCategoryEnum,
    Inventory,
    Organization,
    ProductionLog,
)
from core.db.provisioning import provision_new_organization  # noqa: E402
from core.inr_amount import parse_inr_amount, parse_percent  # noqa: E402

MASTER_INDEX_DEFAULT = ROOT / "factory_output" / "master_index.csv"
SALES_JSON_DEFAULT = ROOT / "vault" / "sales_history.json"
SALES_CSV_DEFAULT = ROOT / "vault" / "sales_history.csv"
SEED_DEFAULT = ROOT / "vault" / "migration_seed.json"
VAULT_DIR = ROOT / "vault"

SKIP_JSON_NAMES = frozenset({"user_profile.json", "agenda_state.json"})
_WEIGHT_KG_RE = re.compile(r"weight_kg\s*=\s*([0-9.eE+-]+)", re.I)
_REVENUE_INR_RE = re.compile(r"revenue_inr\s*=\s*([0-9.eE+-]+)", re.I)
_LOOSE_INR_RE = re.compile(r"(?:revenue|amount|value)[_a-z]*\s*[=:]\s*([^\s;]+)", re.I)


def _dec(x: Any) -> Decimal | None:
    if x is None or x == "":
        return None
    if isinstance(x, Decimal):
        return x
    p = parse_inr_amount(x)
    if p is not None:
        return p
    try:
        return Decimal(str(x))
    except Exception:
        return None


def _parse_note_valuation(note: str) -> Decimal | None:
    if not note:
        return None
    m = _REVENUE_INR_RE.search(note)
    if m:
        try:
            return Decimal(m.group(1))
        except Exception:
            pass
    m2 = _LOOSE_INR_RE.search(note)
    if m2:
        return parse_inr_amount(m2.group(1))
    return None


def _parse_dt(val: str | None) -> datetime | None:
    if not val or not str(val).strip():
        return None
    s = str(val).strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except ValueError:
        try:
            d = date.fromisoformat(s[:10])
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        except ValueError:
            return None


def _parse_seed_date(val: Any) -> date | None:
    if not val:
        return None
    s = str(val).strip()[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _debt_category(val: str) -> DebtCategoryEnum:
    key = (val or "other").strip().lower().replace(" ", "_")
    try:
        return DebtCategoryEnum(key)
    except ValueError:
        return DebtCategoryEnum.other


def _asset_status(val: str) -> AssetStatusEnum:
    key = (val or "active").strip().lower()
    try:
        return AssetStatusEnum(key)
    except ValueError:
        return AssetStatusEnum.active


def load_master_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return [{k: (v or "") for k, v in row.items()} for row in csv.DictReader(f)]


def load_sales_rows(csv_path: Path, json_path: Path) -> list[dict[str, Any]]:
    if csv_path.is_file():
        with csv_path.open(encoding="utf-8", newline="") as f:
            rows = [dict(r) for r in csv.DictReader(f)]
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "invoice_no": r.get("invoice_no", ""),
                    "invoice_date": r.get("invoice_date", ""),
                    "relative_path": (r.get("relative_path") or "").replace("\\", "/").lstrip("/"),
                    "buyer": r.get("buyer", ""),
                    "weight_kg": r.get("weight_kg", ""),
                    "rate_per_kg_inr": r.get("rate_per_kg_inr", ""),
                    "grand_total_inr": r.get("grand_total_inr", ""),
                    "grade": r.get("grade", ""),
                    "saved_at_utc": r.get("saved_at_utc", ""),
                }
            )
        return out
    if json_path.is_file():
        try:
            raw = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if isinstance(raw, list):
            return [x for x in raw if isinstance(x, dict)]
    return []


def discover_extra_sales_from_vault() -> list[dict[str, Any]]:
    """Merge invoice-like lists from vault/**/*.json (excluding state files)."""
    if not VAULT_DIR.is_dir():
        return []
    merged: list[dict[str, Any]] = []
    for path in sorted(VAULT_DIR.rglob("*.json")):
        if path.name in SKIP_JSON_NAMES or path.name in (
            "migration_seed.json",
            "sales_history.json",
        ):
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(raw, list) and raw and isinstance(raw[0], dict):
            if any(k in raw[0] for k in ("invoice_no", "grand_total_inr", "relative_path")):
                merged.extend(x for x in raw if isinstance(x, dict))
    return merged


def load_migration_seed(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _get_org(session, *, name: str, gst: str, industry: str) -> Organization:
    if gst and gst.strip():
        o = session.execute(
            select(Organization).where(Organization.gst_number == gst.strip())
        ).scalar_one_or_none()
        if o:
            return o
    o = session.execute(select(Organization).where(Organization.name == name)).scalar_one_or_none()
    if o:
        return o
    return provision_new_organization(
        session,
        name=name,
        gst_number=gst.strip() or None,
        industry=industry or None,
    )


def _ensure_asset(
    session,
    org: Organization,
    *,
    name: str,
    category: str,
    valuation: Decimal | None,
    external_ref: str | None,
    status: AssetStatusEnum = AssetStatusEnum.active,
) -> Asset:
    if external_ref:
        ex = session.execute(
            select(Asset).where(
                Asset.organization_id == org.id,
                Asset.external_ref == external_ref,
            )
        ).scalar_one_or_none()
        if ex:
            return ex
    a = Asset(
        organization_id=org.id,
        name=name[:2000],
        category=category[:500],
        valuation=valuation,
        status_enum=status,
        external_ref=external_ref,
    )
    session.add(a)
    session.flush()
    return a


def _ensure_inventory(
    session,
    org: Organization,
    *,
    sku: str,
    qty: Decimal,
    location: str,
    unit_price: Decimal | None,
    total_value: Decimal | None,
    external_ref: str | None,
) -> None:
    loc = (location or "").strip()
    sku_t = sku.strip()[:500]
    q = session.execute(
        select(Inventory).where(
            Inventory.organization_id == org.id,
            Inventory.sku_name == sku_t,
            Inventory.location == loc,
        )
    ).scalar_one_or_none()
    if q:
        return
    session.add(
        Inventory(
            organization_id=org.id,
            sku_name=sku_t,
            quantity=qty,
            location=loc,
            unit_price=unit_price,
            total_value=total_value,
            external_ref=external_ref,
        )
    )
    session.flush()


def _ensure_debt(
    session,
    org: Organization,
    *,
    lender: str,
    principal: Decimal,
    rate_pct: float | None,
    start_date: date | None,
    category: DebtCategoryEnum,
    external_ref: str | None,
) -> None:
    if external_ref:
        ex = session.execute(select(Debt).where(Debt.external_ref == external_ref)).scalar_one_or_none()
        if ex:
            return
    session.add(
        Debt(
            organization_id=org.id,
            lender_name=lender[:500],
            principal=principal,
            interest_rate=Decimal(str(rate_pct)) if rate_pct is not None else None,
            start_date=start_date,
            category_enum=category,
            external_ref=external_ref,
        )
    )
    session.flush()


def _ensure_production_log(
    session,
    asset: Asset,
    *,
    ts: datetime,
    unit: str,
    cement: Decimal | None,
    sand: Decimal | None,
    blocks: Decimal | None,
    raw_in: Decimal | None,
    yield_out: Decimal | None,
    labor: Decimal | None,
    external_ref: str | None,
) -> None:
    if external_ref:
        ex = session.execute(
            select(ProductionLog).where(
                ProductionLog.asset_id == asset.id,
                ProductionLog.external_ref == external_ref,
            )
        ).scalar_one_or_none()
        if ex:
            return
    session.add(
        ProductionLog(
            asset_id=asset.id,
            timestamp=ts,
            production_unit=unit[:64],
            cement_in=cement,
            sand_in=sand,
            blocks_out=blocks,
            raw_material_in=raw_in,
            yield_out=yield_out,
            labor_cost=labor,
            external_ref=external_ref,
        )
    )
    session.flush()


def run_migration(
    *,
    dry_run: bool,
    org_name: str,
    gst_number: str,
    industry: str,
    master_path: Path,
    sales_csv_path: Path,
    sales_json_path: Path,
    seed_path: Path,
) -> int:
    url = get_database_url()
    if not url and not dry_run:
        print("ERROR: DATABASE_URL is not set.", file=sys.stderr)
        return 1

    master_rows = load_master_rows(master_path)
    sales_rows = load_sales_rows(sales_csv_path, sales_json_path)
    sales_rows.extend(discover_extra_sales_from_vault())
    seed = load_migration_seed(seed_path)

    print(f"master_index rows: {len(master_rows)}")
    print(f"sales rows (merged): {len(sales_rows)}")
    print(f"migration_seed keys: {list(seed.keys()) if seed else []}")

    if dry_run:
        print("[dry-run] Parsed inputs; no database writes.")
        return 0

    engine = get_engine()
    if engine is None:
        print("ERROR: could not create engine.", file=sys.stderr)
        return 1

    print("DB URL:", normalize_database_url(url or "")[:56] + "...")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    try:
        with Session() as session:
            with session.begin():
                orgs_seed = seed.get("organizations")
                if isinstance(orgs_seed, list) and orgs_seed:
                    for o in orgs_seed:
                        if not isinstance(o, dict):
                            continue
                        _get_org(
                            session,
                            name=str(o.get("name") or org_name),
                            gst=str(o.get("gst_number") or gst_number or ""),
                            industry=str(o.get("industry") or industry),
                        )
                org = _get_org(session, name=org_name, gst=gst_number, industry=industry)

                hb_asset = _ensure_asset(
                    session,
                    org,
                    name="Hollow Block Unit",
                    category="hollow_block",
                    valuation=_dec(seed.get("hollow_block_unit_valuation_inr")),
                    external_ref="asset:hollow_block_unit",
                    status=_asset_status(str(seed.get("hollow_block_status", "active"))),
                )

                for rw in master_rows:
                    rel = (rw.get("relative_path") or "").replace("\\", "/").lstrip("/")
                    title = (rw.get("title") or rel or "row").strip()
                    kind = (rw.get("kind") or "file").strip() or "file"
                    note = rw.get("note") or ""
                    val = _parse_note_valuation(note)
                    name = f"{title} [{rel}]" if rel else title
                    _ensure_asset(
                        session,
                        org,
                        name=name[:2000],
                        category=kind[:500],
                        valuation=val,
                        external_ref=f"master_index:{rel}" if rel else None,
                    )

                assets_by_path: dict[str, Asset] = {}
                for a in session.execute(
                    select(Asset).where(Asset.organization_id == org.id)
                ).scalars().all():
                    if a.external_ref and a.external_ref.startswith("master_index:"):
                        rel = a.external_ref.split(":", 1)[1]
                        assets_by_path[rel] = a

                for sale_idx, rec in enumerate(sales_rows):
                    rel = (rec.get("relative_path") or "").replace("\\", "/").lstrip("/")
                    grade = str(rec.get("grade") or "HDPE")
                    inv_no = str(rec.get("invoice_no") or "")
                    sku = (f"Pipe-{grade}-{inv_no}" if inv_no else f"Pipe-{grade}")[:500]
                    w = _dec(rec.get("weight_kg")) or Decimal("0")
                    rate = _dec(rec.get("rate_per_kg_inr"))
                    grand = _dec(rec.get("grand_total_inr"))
                    ext_inv = f"inv:{rel}|{inv_no}" if rel or inv_no else None
                    _ensure_inventory(
                        session,
                        org,
                        sku=sku,
                        qty=w,
                        location="factory_floor",
                        unit_price=rate,
                        total_value=grand,
                        external_ref=ext_inv,
                    )
                    asset = assets_by_path.get(rel)
                    if asset is None:
                        asset = _ensure_asset(
                            session,
                            org,
                            name=f"Sale [{rel or inv_no or 'unknown'}]"[:2000],
                            category="invoice",
                            valuation=grand,
                            external_ref=f"sale_asset:{rel}" if rel else f"sale_asset:{inv_no}",
                        )
                        if rel:
                            assets_by_path[rel] = asset
                    ts = _parse_dt(str(rec.get("saved_at_utc") or "")) or datetime.now(timezone.utc)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    _ensure_production_log(
                        session,
                        asset,
                        ts=ts,
                        unit="pipe",
                        cement=None,
                        sand=None,
                        blocks=None,
                        raw_in=w,
                        yield_out=w,
                        labor=Decimal("0"),
                        external_ref=f"pipe_sale:{sale_idx}:{rel}:{inv_no}",
                    )

                for item in seed.get("debts") or []:
                    if not isinstance(item, dict):
                        continue
                    principal = _dec(item.get("principal_inr") or item.get("principal"))
                    if principal is None:
                        continue
                    rate = parse_percent(item.get("interest_rate_percent") or item.get("interest_rate"))
                    _ensure_debt(
                        session,
                        org,
                        lender=str(item.get("lender_name") or "Unknown"),
                        principal=principal,
                        rate_pct=rate,
                        start_date=_parse_seed_date(item.get("start_date")),
                        category=_debt_category(str(item.get("category") or "other")),
                        external_ref=str(item["external_ref"])
                        if item.get("external_ref")
                        else f"seed:debt:{item.get('lender_name')}:{principal}",
                    )

                for item in seed.get("assets") or []:
                    if not isinstance(item, dict):
                        continue
                    _ensure_asset(
                        session,
                        org,
                        name=str(item.get("name") or "Asset"),
                        category=str(item.get("category") or "general"),
                        valuation=_dec(item.get("valuation_inr") or item.get("valuation")),
                        external_ref=str(item["external_ref"])
                        if item.get("external_ref")
                        else f"seed:asset:{item.get('name')}",
                        status=_asset_status(str(item.get("status", "active"))),
                    )

                for item in seed.get("inventory") or []:
                    if not isinstance(item, dict):
                        continue
                    qty = _dec(item.get("qty") or item.get("quantity")) or Decimal("0")
                    _ensure_inventory(
                        session,
                        org,
                        sku=str(item.get("sku") or item.get("sku_name") or "SKU"),
                        qty=qty,
                        location=str(item.get("location") or ""),
                        unit_price=_dec(item.get("unit_price_inr")),
                        total_value=_dec(item.get("total_value_inr") or item.get("total_value")),
                        external_ref=str(item["external_ref"])
                        if item.get("external_ref")
                        else None,
                    )

                for item in seed.get("hollow_block_logs") or []:
                    if not isinstance(item, dict):
                        continue
                    ts = _parse_dt(str(item.get("timestamp") or "")) or datetime.now(timezone.utc)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    cement = _dec(item.get("cement_in"))
                    sand = _dec(item.get("sand_in"))
                    blocks = _dec(item.get("blocks_out"))
                    labor = _dec(item.get("labor_cost_inr") or item.get("labor_cost"))
                    ext = str(item.get("external_ref") or f"hb:{ts.isoformat()}:{cement}:{sand}:{blocks}")
                    _ensure_production_log(
                        session,
                        hb_asset,
                        ts=ts,
                        unit="hollow_block",
                        cement=cement,
                        sand=sand,
                        blocks=blocks,
                        raw_in=None,
                        yield_out=None,
                        labor=labor,
                        external_ref=ext[:512],
                    )

        print("OK: migrate_vault committed (single ACID transaction).")
        return 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


def main() -> int:
    p = argparse.ArgumentParser(description="Migrate vault CSV/JSON into PostgreSQL (V2.1).")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--org-name", default="THIRAMAI Sovereign")
    p.add_argument("--gst-number", default="", help='e.g. GST for "Modern Corp"')
    p.add_argument("--industry", default="Manufacturing")
    p.add_argument("--master", type=Path, default=MASTER_INDEX_DEFAULT)
    p.add_argument("--sales-csv", type=Path, default=SALES_CSV_DEFAULT)
    p.add_argument("--sales-json", type=Path, default=SALES_JSON_DEFAULT)
    p.add_argument("--seed", type=Path, default=SEED_DEFAULT, help="vault/migration_seed.json")
    args = p.parse_args()
    return run_migration(
        dry_run=args.dry_run,
        org_name=args.org_name,
        gst_number=args.gst_number,
        industry=args.industry,
        master_path=args.master,
        sales_csv_path=args.sales_csv,
        sales_json_path=args.sales_json,
        seed_path=args.seed,
    )


if __name__ == "__main__":
    raise SystemExit(main())
