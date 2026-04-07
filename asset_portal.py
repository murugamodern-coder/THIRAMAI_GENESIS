"""
Sovereign Asset Portal: list / index PDFs and safe vault files; quick-action links for chat.
"""

from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent
FACTORY_OUTPUT = ROOT / "factory_output"
VAULT_DIR = ROOT / "vault"
MASTER_INDEX_CSV = FACTORY_OUTPUT / "master_index.csv"
SCAN_STATE = FACTORY_OUTPUT / ".asset_scan_state.json"
# Vault JSON backup (not in ALLOWED_VAULT_SUFFIXES — not served or listed in /assets)
SALES_HISTORY_JSON = VAULT_DIR / "sales_history.json"
USER_PROFILE_JSON = VAULT_DIR / "user_profile.json"
DAILY_LOG_TXT = VAULT_DIR / "daily_log.txt"

VAULT_SKIP_NAMES = frozenset({"agenda_state.json", "user_profile.json"})
ALLOWED_VAULT_SUFFIXES = {".pdf", ".txt", ".md", ".csv"}
ALLOWED_FACTORY_SUFFIXES = {".pdf", ".txt", ".md", ".csv"}  # invoices + exports + index

_ORG_ID_IN_NOTE = re.compile(r"organization_id\s*=\s*(\d+)", re.I)


def legacy_default_organization_id() -> int:
    """Untagged master_index rows are attributed to this org (default ``1``)."""
    return int((os.getenv("THIRAMAI_DEFAULT_ORG_ID") or "1").strip() or "1")


def index_note_matches_organization(note: str, organization_id: int) -> bool:
    """True if CSV ``note`` tags ``organization_id=<id>`` or legacy default org applies."""
    m = _ORG_ID_IN_NOTE.search(note or "")
    if m:
        return int(m.group(1)) == int(organization_id)
    return int(organization_id) == legacy_default_organization_id()


def append_organization_to_index_note(note: str, organization_id: int) -> str:
    """Append ``organization_id=`` when missing so /assets and TSI stay tenant-scoped."""
    n = (note or "").strip()
    if _ORG_ID_IN_NOTE.search(n):
        return n
    sep = "; " if n else ""
    return f"{n}{sep}organization_id={int(organization_id)}"


def index_row_visible_for_organization(row: dict[str, str], organization_id: int) -> bool:
    """Whether a master_index row should surface to this tenant (factory note or tenant vault path)."""
    zone = (row.get("zone") or "").strip()
    rel = (row.get("relative_path") or "").replace("\\", "/").lstrip("/")
    note = row.get("note") or ""
    oid = int(organization_id)
    if zone == "factory":
        return index_note_matches_organization(note, oid)
    if zone == "vault":
        return rel.startswith(f"tenants/{oid}/") or index_note_matches_organization(note, oid)
    return index_note_matches_organization(note, oid)


# Humanoid R&D: fraction of *revenue attributed to each full 100 kg* of indexed pipe sales → Robotics Fund
ROBOTICS_FUND_REVENUE_FRACTION_PER_100KG_TRANCHE = 0.02


def _robotics_fund_allocation(total_kg: float, total_revenue: float) -> dict[str, Any]:
    """
    Each completed 100 kg tranche of indexed sales allocates a small % of the revenue
    that would correspond to that tranche (uniform revenue/kg assumption).
    """
    tranches = int(total_kg // 100) if total_kg > 0 else 0
    pct_display = round(ROBOTICS_FUND_REVENUE_FRACTION_PER_100KG_TRANCHE * 100.0, 2)
    if tranches <= 0 or total_kg <= 0 or total_revenue <= 0:
        return {
            "robotics_fund_inr": 0.0,
            "pipe_sales_100kg_tranches": 0,
            "robotics_fund_pct_of_tranche_revenue": pct_display,
            "revenue_inr_per_100kg_tranche": 0.0,
        }
    rev_per_kg = total_revenue / total_kg
    revenue_per_tranche = rev_per_kg * 100.0
    fund = tranches * revenue_per_tranche * ROBOTICS_FUND_REVENUE_FRACTION_PER_100KG_TRANCHE
    return {
        "robotics_fund_inr": round(fund, 2),
        "pipe_sales_100kg_tranches": tranches,
        "robotics_fund_pct_of_tranche_revenue": pct_display,
        "revenue_inr_per_100kg_tranche": round(revenue_per_tranche, 2),
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_factory_root() -> None:
    FACTORY_OUTPUT.mkdir(parents=True, exist_ok=True)


def _load_scan_state() -> dict[str, Any]:
    _ensure_factory_root()
    if not SCAN_STATE.is_file():
        return {"last_index_row_count": 0}
    try:
        data = json.loads(SCAN_STATE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"last_index_row_count": 0}
    except (json.JSONDecodeError, OSError):
        return {"last_index_row_count": 0}


def _save_scan_state(data: dict[str, Any]) -> None:
    _ensure_factory_root()
    SCAN_STATE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def factory_url_for_relative(rel_posix: str) -> str:
    rel = rel_posix.replace("\\", "/").lstrip("/")
    return f"/static/factory/{quote(rel)}"


def vault_url_for_relative(rel_posix: str) -> str:
    rel = rel_posix.replace("\\", "/").lstrip("/")
    parts = rel.split("/")
    enc = "/".join(quote(p) for p in parts)
    return f"/media/vault/{enc}"


def append_master_index_row(
    *,
    zone: str,
    relative_path: str,
    kind: str,
    title: str = "",
    size_bytes: int = 0,
    note: str = "",
) -> None:
    """Append one row to master_index.csv (creates file + header if needed)."""
    _ensure_factory_root()
    rel = relative_path.replace("\\", "/").lstrip("/")
    ts = _utc_now_iso()
    header = [
        "timestamp_utc",
        "zone",
        "relative_path",
        "kind",
        "title",
        "size_bytes",
        "note",
    ]
    write_header = not MASTER_INDEX_CSV.is_file()
    with MASTER_INDEX_CSV.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(header)
        w.writerow([ts, zone, rel, kind, title, size_bytes, note])


def _read_index_rows() -> list[dict[str, str]]:
    if not MASTER_INDEX_CSV.is_file():
        return []
    try:
        with MASTER_INDEX_CSV.open("r", encoding="utf-8", newline="") as f:
            return [{k: (v or "") for k, v in row.items()} for row in csv.DictReader(f)]
    except OSError:
        return []


_WEIGHT_KG_RE = re.compile(r"weight_kg\s*=\s*([0-9.eE+-]+)", re.I)
_REVENUE_INR_RE = re.compile(r"revenue_inr\s*=\s*([0-9.eE+-]+)", re.I)


def append_sales_history_entry(record: dict[str, Any]) -> None:
    """Append one JSON object to vault/sales_history.json (invoice raw backup)."""
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    entry = dict(record)
    entry["saved_at_utc"] = _utc_now_iso()
    entries: list[Any] = []
    if SALES_HISTORY_JSON.is_file():
        try:
            raw = json.loads(SALES_HISTORY_JSON.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                entries = list(raw)
        except (json.JSONDecodeError, OSError):
            entries = []
    entries.append(entry)
    try:
        SALES_HISTORY_JSON.write_text(
            json.dumps(entries, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


def machine_fix_status() -> dict[str, str]:
    """
    Pending machine / plant fix signal from vault (profile blockers + daily log).
    """
    status = "No open item logged"
    detail = ""
    try:
        if USER_PROFILE_JSON.is_file():
            data = json.loads(USER_PROFILE_JSON.read_text(encoding="utf-8"))
            blockers = data.get("current_business_blockers")
            if isinstance(blockers, list):
                for b in blockers:
                    if not isinstance(b, str):
                        continue
                    low = b.lower()
                    if any(
                        k in low
                        for k in (
                            "machine",
                            "hydraulic",
                            "extruder",
                            "extrusion",
                            "plant",
                            "idle",
                            "downtime",
                        )
                    ):
                        status = "Pending"
                        detail = b.strip()
                        break
    except (json.JSONDecodeError, OSError, TypeError):
        pass
    if status == "No open item logged" and DAILY_LOG_TXT.is_file():
        try:
            text = DAILY_LOG_TXT.read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines():
                s = line.strip()
                if not s.upper().startswith("TASK:"):
                    continue
                low = s.lower()
                if "machine" in low or "hydraulic" in low or "extruder" in low:
                    status = "Pending"
                    detail = s.replace("TASK:", "").strip()
                    break
        except OSError:
            pass
    return {"status": status, "detail": detail}


def _financial_performance_summary_safe_default(*, reason: str = "") -> dict[str, Any]:
    """Non-throwing fallback for empty/corrupt index or any aggregation failure."""
    liquidity_inr = 250_000.0
    machine_restart_inr = 150_000.0
    return {
        "total_weight_kg": 0.0,
        "total_tonnage": 0.0,
        "total_revenue_inr": 0.0,
        "invoice_rows_with_weight": 0,
        "invoice_rows_with_revenue_inr": 0,
        "sales_history_backup_entries": 0,
        "machine_fix_status": "",
        "machine_fix_detail": "",
        "estimated_stock_kg": 0.0,
        "cash_flow_radar": {
            "liquidity_inr": liquidity_inr,
            "machine_restart_inr": machine_restart_inr,
            "indexed_sales_kg": 0.0,
            "indexed_revenue_inr": 0.0,
            "remaining_cash_after_restart_inr": round(liquidity_inr - machine_restart_inr, 2),
            "net_after_restart_plus_revenue_inr": round(liquidity_inr - machine_restart_inr, 2),
            **_robotics_fund_allocation(0.0, 0.0),
        },
        "procurement_alert": {
            "active": False,
            "headline": "",
            "message": "",
            "detail": "",
        },
        "material_shortage_alert": {
            "active": False,
            "headline": "",
            "message": "",
            "detail": "",
        },
        "tsi": {
            "score": 10,
            "band": "Initial Seed",
            "label": "Total Sovereign Intelligence (TSI)",
        },
        "tsi_safe_mode": True,
        "tsi_safe_reason": (reason or "empty_index_or_internal_error").strip(),
    }


def _financial_performance_summary_impl(*, organization_id: int | None = None) -> dict[str, Any]:
    """
    Aggregate invoice rows in master_index.csv: tonnage (kg), revenue (INR when note has revenue_inr=).

    When ``organization_id`` is set, only rows tagged for that org (or legacy default) are included.
    """
    rows = _read_index_rows()
    if organization_id is not None:
        rows = [r for r in rows if index_row_visible_for_organization(r, int(organization_id))]
    total_kg = 0.0
    total_revenue = 0.0
    invoices_with_weight = 0
    invoices_with_revenue = 0
    for rw in rows:
        if (rw.get("kind") or "").strip().lower() != "invoice":
            continue
        note = rw.get("note") or ""
        wm = _WEIGHT_KG_RE.search(note)
        if wm:
            try:
                total_kg += float(wm.group(1))
                invoices_with_weight += 1
            except ValueError:
                pass
        rm = _REVENUE_INR_RE.search(note)
        if rm:
            try:
                total_revenue += float(rm.group(1))
                invoices_with_revenue += 1
            except ValueError:
                pass
    backup_count = 0
    if SALES_HISTORY_JSON.is_file():
        try:
            raw = json.loads(SALES_HISTORY_JSON.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                backup_count = len(raw)
        except (json.JSONDecodeError, OSError):
            pass
    m = machine_fix_status()
    try:
        from factory import machine_sensor as _twin

        _ts = _twin.load_state()
        est_stock = float(_ts.get("estimated_stock_kg", 0.0))
        twin_running = (
            bool(_ts.get("operator_running"))
            and bool(_ts.get("hydraulic_fixed"))
            and not bool(_ts.get("maintenance_mode"))
        )
    except Exception:
        est_stock = 0.0
        twin_running = False

    liquidity_inr = 250_000.0
    machine_restart_inr = 150_000.0
    rd_fund = _robotics_fund_allocation(total_kg, total_revenue)
    cash_flow_radar = {
        "liquidity_inr": liquidity_inr,
        "machine_restart_inr": machine_restart_inr,
        "indexed_sales_kg": round(total_kg, 4),
        "indexed_revenue_inr": round(total_revenue, 2),
        "remaining_cash_after_restart_inr": round(liquidity_inr - machine_restart_inr, 2),
        "net_after_restart_plus_revenue_inr": round(liquidity_inr - machine_restart_inr + total_revenue, 2),
        **rd_fund,
    }

    try:
        from factory import market_watch as _mw

        procurement_alert = _mw.procurement_alert_payload()
    except Exception:
        procurement_alert = {
            "active": False,
            "headline": "",
            "message": "",
            "detail": "",
        }

    try:
        from factory import fab_engine as _fab

        material_shortage_alert = _fab.material_shortage_alert_payload()
    except Exception:
        material_shortage_alert = {
            "active": False,
            "headline": "",
            "message": "",
            "detail": "",
        }

    proc_on = bool(
        isinstance(procurement_alert, dict) and procurement_alert.get("active")
    )
    ms_st = (m.get("status") or "").strip()
    # Empty master index (missing or zero rows): universal safe baseline — never divide or assume rows exist.
    index_empty = not MASTER_INDEX_CSV.is_file() or len(rows) == 0
    if index_empty:
        tsi = 10
        band = "Initial Seed"
    else:
        score_f = 36.0
        if total_revenue > 0:
            score_f += min(20.0, 5.0 + total_revenue / 2000.0)
        if total_kg >= 16.0:
            score_f += 14.0
        elif total_kg > 0:
            score_f += 7.0
        if est_stock > 0:
            score_f += 6.0
        if backup_count > 0:
            score_f += 4.0
        if proc_on:
            score_f += 8.0
        if ms_st == "Pending":
            score_f -= 10.0
        elif ms_st == "No open item logged":
            score_f += 4.0
        if twin_running:
            score_f += 10.0
        tsi = int(max(0, min(100, round(score_f))))
        if tsi >= 75:
            band = "Sovereign Prime"
        elif tsi >= 55:
            band = "Empire Ascendant"
        elif tsi >= 35:
            band = "Foundation Build"
        else:
            band = "Recalibrate"

    return {
        "total_weight_kg": round(total_kg, 4),
        "total_tonnage": round(total_kg / 1000.0, 6),
        "total_revenue_inr": round(total_revenue, 2),
        "invoice_rows_with_weight": invoices_with_weight,
        "invoice_rows_with_revenue_inr": invoices_with_revenue,
        "sales_history_backup_entries": backup_count,
        "machine_fix_status": m.get("status", ""),
        "machine_fix_detail": m.get("detail", ""),
        "estimated_stock_kg": round(float(est_stock), 4),
        "cash_flow_radar": cash_flow_radar,
        "procurement_alert": procurement_alert,
        "material_shortage_alert": material_shortage_alert,
        "tsi": {"score": tsi, "band": band, "label": "Total Sovereign Intelligence (TSI)"},
        "tsi_safe_mode": index_empty,
        "tsi_safe_reason": ("master_index empty or missing — Initial Seed baseline" if index_empty else ""),
    }


def financial_performance_summary() -> dict[str, Any]:
    """Public API: never raises; safe TSI + radar defaults on failure (all index rows — smoke / CLI)."""
    try:
        return _financial_performance_summary_impl(organization_id=None)
    except Exception as exc:
        return _financial_performance_summary_safe_default(reason=type(exc).__name__)


def financial_performance_summary_for_organization(organization_id: int) -> dict[str, Any]:
    """TSI-style summary scoped to one tenant (JWT ``organization_id``)."""
    try:
        return _financial_performance_summary_impl(organization_id=int(organization_id))
    except Exception as exc:
        return _financial_performance_summary_safe_default(reason=type(exc).__name__)


def drain_new_index_rows() -> list[dict[str, str]]:
    """
    Pop rows appended to master_index.csv since last /chat (row-count cursor).
    Returns new row dicts (CSV columns); advances cursor.
    """
    _ensure_factory_root()
    state = _load_scan_state()
    rows = _read_index_rows()

    if "last_index_row_count" not in state:
        state["last_index_row_count"] = len(rows)
        _save_scan_state(state)
        return []

    last_n = int(state.get("last_index_row_count", 0))
    if len(rows) <= last_n:
        return []

    new_rows = rows[last_n:]
    state["last_index_row_count"] = len(rows)
    _save_scan_state(state)
    return new_rows


def drain_new_index_rows_for_organization(organization_id: int) -> list[dict[str, str]]:
    """
    Like ``drain_new_index_rows`` but only returns rows visible to this organization and tracks
    a per-tenant cursor in ``.asset_scan_state.json`` (``last_index_row_count_by_org``).
    """
    _ensure_factory_root()
    state = _load_scan_state()
    rows = _read_index_rows()
    oid = int(organization_id)
    oid_s = str(oid)
    raw_by_org = state.get("last_index_row_count_by_org")
    by_org: dict[str, int] = raw_by_org if isinstance(raw_by_org, dict) else {}
    if not isinstance(raw_by_org, dict):
        state["last_index_row_count_by_org"] = by_org
    last_n = int(by_org.get(oid_s) or state.get("last_index_row_count", 0) or 0)
    if len(rows) <= last_n:
        return []
    new_rows = rows[last_n:]
    filtered = [r for r in new_rows if index_row_visible_for_organization(r, oid)]
    by_org[oid_s] = len(rows)
    state["last_index_row_count_by_org"] = by_org
    _save_scan_state(state)
    return filtered


def quick_action_rows_to_payload(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """UI / JSON: label, url, kind, zone."""
    out: list[dict[str, str]] = []
    for rw in rows:
        zone = (rw.get("zone") or "").strip()
        rel = (rw.get("relative_path") or "").strip()
        kind = (rw.get("kind") or "file").strip()
        title = (rw.get("title") or Path(rel).name).strip() or rel
        if zone == "factory":
            url = factory_url_for_relative(rel)
        else:
            url = vault_url_for_relative(rel)
        out.append({"label": title, "url": url, "kind": kind, "zone": zone})
    return out


def sync_index_cursor_to_end() -> None:
    """After serving a direct download link (e.g. POST invoice), skip duplicate Quick Action on next /chat."""
    _ensure_factory_root()
    state = _load_scan_state()
    state["last_index_row_count"] = len(_read_index_rows())
    _save_scan_state(state)


def format_quick_actions_markdown(rows: list[dict[str, str]]) -> str:
    if not rows:
        return ""
    lines = [
        "### SaaS Factory — Quick Action",
        "Sovereign Leader, your file is ready — use the **Sovereign Asset Vault** or the links below:",
    ]
    for item in quick_action_rows_to_payload(rows):
        u = item["url"]
        lines.append(
            f"- **{item['kind']}**: [{item['label']}]({u}) — [Click here to view]({u})"
        )
    return "\n".join(lines)


def format_recent_factory_assets_markdown_for_personal(
    *, organization_id: int, limit: int = 8, within_hours: float = 168
) -> str:
    """
    Markdown links for recent factory rows in master_index.csv for one tenant
    (personal / vault-priority queries).
    """
    from datetime import datetime, timezone

    rows = _read_index_rows()
    factory = [
        r
        for r in rows
        if (r.get("zone") or "").strip() == "factory"
        and index_row_visible_for_organization(r, int(organization_id))
    ]
    factory.sort(key=lambda r: (r.get("timestamp_utc") or "").strip(), reverse=True)
    now = datetime.now(timezone.utc)
    lines = [
        "### Recent indexed factory assets",
        "_Same-origin links — open in browser:_",
    ]
    n = 0
    for rw in factory:
        if n >= limit:
            break
        ts_s = (rw.get("timestamp_utc") or "").strip()
        if ts_s and within_hours > 0:
            try:
                ts = datetime.fromisoformat(ts_s.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if (now - ts).total_seconds() > within_hours * 3600:
                    continue
            except ValueError:
                pass
        rel = (rw.get("relative_path") or "").strip().replace("\\", "/")
        if not rel:
            continue
        url = factory_url_for_relative(rel)
        title = (rw.get("title") or Path(rel).name).strip()
        lines.append(f"- **{title}** — [View file]({url})")
        n += 1
    if n == 0:
        return ""
    return "\n".join(lines)


def _is_safe_rel(rel: str, *, zone: str) -> bool:
    if not rel or rel.startswith("/") or ".." in rel.split("/"):
        return False
    p = Path(rel)
    if p.is_absolute():
        return False
    return True


def resolve_factory_file(rel: str) -> Path | None:
    if not _is_safe_rel(rel, zone="factory"):
        return None
    full = (FACTORY_OUTPUT / rel).resolve()
    try:
        full.relative_to(FACTORY_OUTPUT.resolve())
    except ValueError:
        return None
    if not full.is_file():
        return None
    if full.name.startswith("."):
        return None
    if full.suffix.lower() not in ALLOWED_FACTORY_SUFFIXES and full.name != "master_index.csv":
        return None
    return full


def resolve_vault_file(rel: str) -> Path | None:
    if not _is_safe_rel(rel, zone="vault"):
        return None
    full = (VAULT_DIR / rel).resolve()
    try:
        full.relative_to(VAULT_DIR.resolve())
    except ValueError:
        return None
    if not full.is_file():
        return None
    if full.name in VAULT_SKIP_NAMES:
        return None
    if full.suffix.lower() not in ALLOWED_VAULT_SUFFIXES:
        return None
    return full


def _index_latest_ts_by_relative_path() -> dict[str, str]:
    """Map factory relative_path -> latest timestamp_utc from master_index.csv (newest wins)."""
    best: dict[str, str] = {}
    for rw in _read_index_rows():
        rel = (rw.get("relative_path") or "").strip().replace("\\", "/")
        ts = (rw.get("timestamp_utc") or "").strip()
        if not rel or not ts:
            continue
        if rel not in best or ts > best[rel]:
            best[rel] = ts
    return best


def list_assets(query: str | None = None) -> list[dict[str, Any]]:
    """All listable files under factory_output/ and vault/ with browser URLs."""
    _ensure_factory_root()
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    q = (query or "").strip().lower()
    items: list[dict[str, Any]] = []

    if FACTORY_OUTPUT.is_dir():
        for path in sorted(FACTORY_OUTPUT.rglob("*")):
            if not path.is_file():
                continue
            if path.name.startswith("."):
                continue
            try:
                rel = path.relative_to(FACTORY_OUTPUT).as_posix()
            except ValueError:
                continue
            suf = path.suffix.lower()
            if suf not in ALLOWED_FACTORY_SUFFIXES and path.name != "master_index.csv":
                continue
            st = path.stat()
            url = factory_url_for_relative(rel)
            kind = "Invoice" if "invoice" in path.name.lower() and suf == ".pdf" else "Factory output"
            if "master_index" in path.name.lower():
                kind = "Index"
            row = {
                "name": path.name,
                "relative_path": rel,
                "zone": "factory",
                "kind": kind,
                "bytes": st.st_size,
                "mtime_iso": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
                "url": url,
                "open_url": url,
            }
            hay = f"{row['name']} {rel} {kind}".lower()
            if not q or q in hay:
                items.append(row)

    if VAULT_DIR.is_dir():
        for path in sorted(VAULT_DIR.rglob("*")):
            if not path.is_file():
                continue
            if path.name in VAULT_SKIP_NAMES:
                continue
            suf = path.suffix.lower()
            if suf not in ALLOWED_VAULT_SUFFIXES:
                continue
            try:
                rel = path.relative_to(VAULT_DIR).as_posix()
            except ValueError:
                continue
            st = path.stat()
            url = vault_url_for_relative(rel)
            kind = "Vault document"
            if suf == ".pdf":
                kind = "PDF (vault)"
            row = {
                "name": path.name,
                "relative_path": rel,
                "zone": "vault",
                "kind": kind,
                "bytes": st.st_size,
                "mtime_iso": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
                "url": url,
                "open_url": url,
            }
            hay = f"{row['name']} {rel} {kind}".lower()
            if not q or q in hay:
                items.append(row)

    # Prefer master_index.csv recency so newest registered PDFs float to top
    idx_ts = _index_latest_ts_by_relative_path()
    for row in items:
        rel = (row.get("relative_path") or "").replace("\\", "/")
        row["index_timestamp_utc"] = idx_ts.get(rel, "")
    items.sort(
        key=lambda x: (x.get("index_timestamp_utc") or "", x.get("mtime_iso") or ""),
        reverse=True,
    )
    return items


def list_assets_for_organization(organization_id: int, query: str | None = None) -> list[dict[str, Any]]:
    """
    Tenant-scoped asset list:

    - **Factory:** files referenced in ``master_index.csv`` with a matching ``organization_id`` tag
      (or legacy untagged rows for ``THIRAMAI_DEFAULT_ORG_ID``).
    - **Vault:** only files under ``vault/tenants/<organization_id>/``.
    """
    _ensure_factory_root()
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    q = (query or "").strip().lower()
    items: list[dict[str, Any]] = []
    oid = int(organization_id)

    tenant_root = VAULT_DIR / "tenants" / str(oid)
    if tenant_root.is_dir():
        for path in sorted(tenant_root.rglob("*")):
            if not path.is_file() or path.name.startswith("."):
                continue
            suf = path.suffix.lower()
            if suf not in ALLOWED_VAULT_SUFFIXES:
                continue
            try:
                rel = path.relative_to(VAULT_DIR).as_posix()
            except ValueError:
                continue
            st = path.stat()
            url = vault_url_for_relative(rel)
            row = {
                "name": path.name,
                "relative_path": rel,
                "zone": "vault",
                "kind": "PDF (tenant vault)" if suf == ".pdf" else "Vault document",
                "bytes": st.st_size,
                "mtime_iso": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
                "url": url,
                "open_url": url,
            }
            hay = f"{row['name']} {rel} {row['kind']}".lower()
            if not q or q in hay:
                items.append(row)

    seen_factory: set[str] = set()
    for rw in _read_index_rows():
        if (rw.get("zone") or "").strip() != "factory":
            continue
        rel = (rw.get("relative_path") or "").strip().replace("\\", "/")
        if not rel or rel in seen_factory:
            continue
        if not index_note_matches_organization(rw.get("note") or "", oid):
            continue
        seen_factory.add(rel)
        path = FACTORY_OUTPUT / rel
        if not path.is_file() or path.name.startswith("."):
            continue
        suf = path.suffix.lower()
        if suf not in ALLOWED_FACTORY_SUFFIXES and path.name != "master_index.csv":
            continue
        st = path.stat()
        url = factory_url_for_relative(rel)
        kind = "Invoice" if "invoice" in path.name.lower() and suf == ".pdf" else "Factory output"
        if "master_index" in path.name.lower():
            kind = "Index"
        row = {
            "name": path.name,
            "relative_path": rel,
            "zone": "factory",
            "kind": kind,
            "bytes": st.st_size,
            "mtime_iso": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            "url": url,
            "open_url": url,
        }
        hay = f"{row['name']} {rel} {kind}".lower()
        if not q or q in hay:
            items.append(row)

    idx_ts = _index_latest_ts_by_relative_path()
    for row in items:
        rel = (row.get("relative_path") or "").replace("\\", "/")
        row["index_timestamp_utc"] = idx_ts.get(rel, "")
    items.sort(
        key=lambda x: (x.get("index_timestamp_utc") or "", x.get("mtime_iso") or ""),
        reverse=True,
    )
    return items


def index_existing_pdfs_scan() -> int:
    """One-time style scan: add master_index rows for PDFs under factory_output not yet in index (by path)."""
    if not MASTER_INDEX_CSV.is_file():
        return 0
    try:
        with MASTER_INDEX_CSV.open("r", encoding="utf-8", newline="") as f:
            seen = {row.get("relative_path", "") for row in csv.DictReader(f)}
    except OSError:
        seen = set()
    n = 0
    for path in FACTORY_OUTPUT.rglob("*.pdf"):
        if not path.is_file() or path.name.startswith("."):
            continue
        rel = path.relative_to(FACTORY_OUTPUT).as_posix()
        if rel in seen:
            continue
        st = path.stat()
        append_master_index_row(
            zone="factory",
            relative_path=rel,
            kind="invoice" if "invoice" in path.name.lower() else "pdf",
            title=path.name,
            size_bytes=st.st_size,
            note="backfill_scan",
        )
        n += 1
    return n
