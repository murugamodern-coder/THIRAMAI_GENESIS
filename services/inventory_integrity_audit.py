"""
Full inventory integrity audit: on-hand vs bills + stock-update audit trail, anomaly scan, correction plan.

Read-only audit posts a **System: Audit Report** to the thought stream. Applying corrections is explicit:
``run_auto_repair`` with ``target=inventory_sync`` (tenant-scoped).
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from core.database import db_session, get_session_factory
from core.db.models import Bill, Inventory, SystemAuditLog
from services.audit_log import ACTION_STOCK_UPDATE
from services.inventory_ops import apply_inventory_delta
from services.thought_stream import append_thought

_LOG = logging.getLogger(__name__)
_ROOT = Path(__file__).resolve().parents[1]
_VAR = _ROOT / "var"


def _audit_cache_path(organization_id: int) -> Path:
    _VAR.mkdir(parents=True, exist_ok=True)
    return _VAR / f"inventory_integrity_audit_org_{int(organization_id)}.json"


def _decimal(x: Any) -> Decimal | None:
    if x is None:
        return None
    try:
        return Decimal(str(x))
    except Exception:
        return None


def _aggregate_bills_sold(session: Session, organization_id: int) -> dict[str, Decimal]:
    """Sum retail quantities sold per sku_name from ``bills.items`` JSON."""
    oid = int(organization_id)
    sold: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    stmt = select(Bill).where(Bill.organization_id == oid)
    for bill in session.scalars(stmt):
        items = bill.items
        if not isinstance(items, list):
            continue
        for line in items:
            if not isinstance(line, dict):
                continue
            sku = str(line.get("sku_name") or "").strip()
            if not sku:
                continue
            q = _decimal(line.get("quantity"))
            if q is None or q <= 0:
                continue
            sold[sku] += q
    return dict(sold)


def _aggregate_audit_stock_deltas(session: Session, organization_id: int) -> dict[str, Decimal]:
    """Sum signed deltas from ``system_audit_logs`` for ``stock_update`` (best-effort metadata)."""
    oid = int(organization_id)
    net: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    try:
        stmt = select(SystemAuditLog).where(
            SystemAuditLog.organization_id == oid,
            SystemAuditLog.action == ACTION_STOCK_UPDATE,
        )
        for row in session.scalars(stmt):
            meta = row.audit_metadata if isinstance(row.audit_metadata, dict) else {}
            sku = str(meta.get("sku") or meta.get("sku_name") or "").strip()
            if not sku:
                continue
            d = _decimal(meta.get("delta"))
            if d is None:
                continue
            net[sku] += d
    except (ProgrammingError, OperationalError) as exc:
        _LOG.debug("inventory_audit audit_log scan skipped: %s", exc)
    return dict(net)


def _inventory_rows_for_org(session: Session, organization_id: int) -> list[Inventory]:
    oid = int(organization_id)
    stmt = select(Inventory).where(
        or_(Inventory.organization_id == oid, Inventory.organization_id.is_(None))
    )
    return list(session.scalars(stmt).all())


def _skus_with_inventory(session: Session, organization_id: int) -> set[str]:
    return {str(r.sku_name or "").strip() for r in _inventory_rows_for_org(session, organization_id) if r.sku_name}


def run_full_inventory_integrity_audit(organization_id: int) -> dict[str, Any]:
    """
    Compare on-hand inventory to bill history and audit-log deltas; scan negatives and orphans.

    Returns a JSON-serializable dict including ``corrections`` (for ``inventory_sync``) and ``thought_report``.
    """
    oid = int(organization_id)
    factory = get_session_factory()
    if factory is None:
        return {
            "ok": False,
            "error": "database_not_configured",
            "organization_id": oid,
            "corrections": [],
            "thought_report": "System: Audit Report — database not configured; cannot audit inventory.",
        }

    negative_rows: list[dict[str, Any]] = []
    corrections: list[dict[str, Any]] = []
    orphaned_bill_skus: list[str] = []
    implied_opening_warnings: list[dict[str, Any]] = []
    qty_by_sku: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    detached_orm_note = (
        "DetachedInstanceError risk: keep a single Session open until attributes are read after commit; "
        "use ``core.database.db_session()`` and ``session.refresh(instance)`` after inventory mutations "
        "(see ``_handle_inventory_adjust``)."
    )

    with factory() as session:
        rows = _inventory_rows_for_org(session, oid)
        sold_by_sku = _aggregate_bills_sold(session, oid)
        audit_delta_by_sku = _aggregate_audit_stock_deltas(session, oid)
        inv_skus = _skus_with_inventory(session, oid)

        for sku, _ in sold_by_sku.items():
            if sku not in inv_skus:
                orphaned_bill_skus.append(sku)

        for r in rows:
            sku = str(r.sku_name or "").strip()
            loc = str(r.location or "").strip()
            q = r.quantity or Decimal("0")
            if sku:
                qty_by_sku[sku] += q
            if q < 0:
                neg = {
                    "inventory_id": int(r.id),
                    "sku_name": sku,
                    "location": loc,
                    "current_quantity": float(q),
                }
                negative_rows.append(neg)
                # Bring row to zero: add -q (positive adjustment when q is negative)
                corrections.append(
                    {
                        "kind": "clamp_negative_to_zero",
                        "inventory_id": int(r.id),
                        "sku_name": sku,
                        "location": loc,
                        "current_quantity": float(q),
                        "correction_delta": float(-q),
                    }
                )

        for sku, sold_total in sold_by_sku.items():
            on_hand = qty_by_sku.get(sku, Decimal("0"))
            implied_opening = on_hand + sold_total
            if implied_opening < Decimal("0"):
                implied_opening_warnings.append(
                    {
                        "sku_name": sku,
                        "on_hand_sum_locations": float(on_hand),
                        "lifetime_sold_from_bills": float(sold_total),
                        "implied_opening_if_bills_only": float(implied_opening),
                        "note": "Negative implied opening if only POS bills removed stock — check receipts, adjustments, or missing inventory rows.",
                    }
                )

    mismatch_count = len(negative_rows) + len(orphaned_bill_skus) + len(implied_opening_warnings)

    result: dict[str, Any] = {
        "ok": True,
        "organization_id": oid,
        "audited_at_unix": time.time(),
        "inventory_row_count": len(rows),
        "negative_stock_rows": negative_rows,
        "orphaned_bill_skus": sorted(set(orphaned_bill_skus)),
        "implied_opening_warnings": implied_opening_warnings,
        "sold_by_sku_from_bills": {k: float(v) for k, v in sorted(sold_by_sku.items())},
        "net_delta_by_sku_from_audit_logs": {k: float(v) for k, v in sorted(audit_delta_by_sku.items())},
        "on_hand_sum_by_sku": {k: float(v) for k, v in sorted(qty_by_sku.items())},
        "orm_session_note": detached_orm_note,
        "corrections": corrections,
        "mismatch_count": mismatch_count,
        "pending_operator_approval": True,
        "approval_hint": (
            "To apply automated corrections (negative stock clamp-to-zero only), confirm: "
            "run_auto_repair with target inventory_sync for this organization."
        ),
    }

    # Human-readable block for thought stream
    lines = [
        "System: Audit Report — Full Inventory Integrity Audit",
        f"Organization ID: {oid}",
        f"Inventory rows scanned: {len(rows)}",
        f"Negative stock rows: {len(negative_rows)}",
        f"SKUs in bills with no inventory row: {len(result['orphaned_bill_skus'])}",
        f"Implied-opening warnings (bills vs on-hand): {len(implied_opening_warnings)}",
        f"Auto-calculated correction deltas (clamp negatives to zero): {len(corrections)}",
        "",
        "ORM / session: " + detached_orm_note,
        "",
        result["approval_hint"],
    ]
    if negative_rows:
        lines.append("")
        lines.append("Negative on-hand:")
        for n in negative_rows[:40]:
            lines.append(f"  - id={n['inventory_id']} sku={n['sku_name']!r} loc={n['location']!r} qty={n['current_quantity']}")
        if len(negative_rows) > 40:
            lines.append(f"  ... +{len(negative_rows) - 40} more")
    if orphaned_bill_skus:
        lines.append("")
        lines.append("Orphaned (bills reference SKU, no inventory row):")
        for s in sorted(set(orphaned_bill_skus))[:40]:
            lines.append(f"  - {s!r}")
        if len(orphaned_bill_skus) > 40:
            lines.append(f"  ... +{len(set(orphaned_bill_skus)) - 40} more")
    if implied_opening_warnings:
        lines.append("")
        lines.append("Integrity warnings (sample):")
        for w in implied_opening_warnings[:20]:
            lines.append(
                f"  - {w['sku_name']!r}: on_hand={w['on_hand_sum_locations']} sold_bills={w['lifetime_sold_from_bills']} implied_opening={w['implied_opening_if_bills_only']}"
            )
    if corrections:
        lines.append("")
        lines.append("Proposed corrections (apply via inventory_sync):")
        for c in corrections[:30]:
            lines.append(
                f"  - {c['sku_name']!r} @ {c['location']!r}: delta +{c['correction_delta']} (from {c['current_quantity']})"
            )
        if len(corrections) > 30:
            lines.append(f"  ... +{len(corrections) - 30} more")

    thought_report = "\n".join(lines)
    result["thought_report"] = thought_report

    try:
        payload = json.loads(json.dumps(result, default=str))
        _audit_cache_path(oid).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        _LOG.warning("inventory audit cache write failed: %s", exc)

    return result


def emit_audit_report_to_thought_stream(
    organization_id: int,
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Run audit, append the System report to the JARVIS thought stream, return the audit dict."""
    audit = run_full_inventory_integrity_audit(int(organization_id))
    body = audit.get("thought_report") or "System: Audit Report — empty."
    chunk = 15000
    for i in range(0, len(body), chunk):
        append_thought(
            body[i : i + chunk],
            phase="audit",
            agent="jarvis",
            request_id=request_id,
            meta={"organization_id": int(organization_id), "audit_ok": bool(audit.get("ok"))},
        )
    return audit


def apply_inventory_integrity_corrections(organization_id: int) -> dict[str, Any]:
    """
    Apply only ``clamp_negative_to_zero`` corrections from a fresh audit (tenant-scoped).

    Intended after operator approval via ``run_auto_repair --target inventory_sync``.
    """
    oid = int(organization_id)
    audit = run_full_inventory_integrity_audit(oid)
    if not audit.get("ok"):
        return {"ok": False, "error": audit.get("error") or "audit_failed", "applied": []}

    applied: list[dict[str, Any]] = []
    errors: list[str] = []

    for c in audit.get("corrections") or []:
        if not isinstance(c, dict) or c.get("kind") != "clamp_negative_to_zero":
            continue
        sku = str(c.get("sku_name") or "").strip()
        loc = str(c.get("location") or "").strip()
        delta = _decimal(c.get("correction_delta"))
        if not sku or delta is None or delta == 0:
            continue
        try:
            with db_session() as session:
                with session.begin():
                    apply_inventory_delta(
                        session,
                        organization_id=oid,
                        sku_name=sku,
                        location=loc,
                        delta=delta,
                    )
        except Exception as exc:
            _LOG.exception("inventory_sync apply failed sku=%r", sku)
            errors.append(f"{sku}@{loc}: {type(exc).__name__}: {exc}")
            continue
        applied.append({"sku_name": sku, "location": loc, "delta": str(delta)})

    ok = not errors
    return {
        "ok": ok,
        "organization_id": oid,
        "applied": applied,
        "errors": errors,
        "note": "Only negative stock clamp corrections were applied; review orphaned SKUs and warnings manually.",
    }
