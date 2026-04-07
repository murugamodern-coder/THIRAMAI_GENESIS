"""Read-only snapshot of org / assets / debts / inventory / production for LLM context."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from core.database import get_engine, get_session_factory
from core.db.models import Asset, Debt, Inventory, Organization, ProductionLog


def _fmt_money(v: Decimal | None) -> str:
    if v is None:
        return "—"
    return f"₹{v:,.2f}"


def fetch_database_vault_context(max_chars: int = 2400, *, organization_id: int) -> str | None:
    """
    Markdown snapshot of PostgreSQL rows for **one organization only** (tenant boundary).

    Returns None if the DB is unavailable. Never mixes assets/inventory/debts/logs from other orgs.
    """
    if get_engine() is None:
        return None
    factory = get_session_factory()
    if factory is None:
        return None

    oid = int(organization_id)
    lines: list[str] = [
        "## Structured vault (PostgreSQL)",
        f"_Tenant organization_id={oid} | UTC: {datetime.now(timezone.utc).isoformat()}_",
        "",
    ]

    try:
        with factory() as session:
            org = session.get(Organization, oid)
            if org is None:
                lines.append(f"_No organization row for id **{oid}**._")
                text = "\n".join(lines).strip()
                return text if len(text) <= max_chars else text[: max_chars - 40] + "\n[... clipped ...]"

            lines.append("### Organization")
            gst = f" | GST **{org.gst_number}**" if org.gst_number else ""
            ind = f" | {org.industry}" if org.industry else ""
            pl = f" | plan **{org.plan}**" if getattr(org, "plan", None) else ""
            lines.append(f"- **{org.name}** (id={org.id}){gst}{ind}{pl}")
            lines.append("")

            assets = session.execute(
                select(Asset)
                .where(Asset.organization_id == oid)
                .order_by(Asset.id.desc())
                .limit(25)
            ).scalars().all()
            if assets:
                lines.append("### Assets (plant / equipment)")
                for a in assets:
                    ref = f" ref=`{a.external_ref}`" if a.external_ref else ""
                    lines.append(
                        f"- [{a.category}] {a.name} — valuation {_fmt_money(a.valuation)} — {a.status_enum.value}{ref}"
                    )
                lines.append("")

            debts = session.execute(
                select(Debt)
                .where(Debt.organization_id == oid)
                .order_by(Debt.id.desc())
                .limit(20)
            ).scalars().all()
            if debts:
                lines.append("### Debts (lender book)")
                for d in debts:
                    r = f"{d.interest_rate}%" if d.interest_rate is not None else "—"
                    due = f" due **{d.due_date}**" if getattr(d, "due_date", None) else ""
                    lines.append(
                        f"- {d.lender_name}: principal {_fmt_money(d.principal)} @ **{r}** p.a. ({d.category_enum.value}){due}"
                    )
                lines.append("")

            inv = session.execute(
                select(Inventory)
                .where(Inventory.organization_id == oid)
                .order_by(Inventory.id.desc())
                .limit(25)
            ).scalars().all()
            if inv:
                lines.append("### Inventory")
                for row in inv:
                    loc = f" @ **{row.location}**" if row.location else ""
                    lines.append(
                        f"- {row.sku_name}{loc}: qty {row.quantity} @ {_fmt_money(row.unit_price)} → {_fmt_money(row.total_value)}"
                    )
                lines.append("")

            logs = session.execute(
                select(ProductionLog)
                .join(Asset, ProductionLog.asset_id == Asset.id)
                .where(Asset.organization_id == oid)
                .order_by(ProductionLog.timestamp.desc())
                .limit(15)
            ).scalars().all()
            if logs:
                lines.append("### Production logs")
                for lg in logs:
                    ts = lg.timestamp.isoformat() if lg.timestamp else ""
                    if lg.production_unit == "hollow_block":
                        lines.append(
                            f"- {ts} | **Hollow block** | cement_in={lg.cement_in} sand_in={lg.sand_in} "
                            f"blocks_out={lg.blocks_out} | labor {_fmt_money(lg.labor_cost)}"
                        )
                    else:
                        lines.append(
                            f"- {ts} | {lg.production_unit} | raw_in={lg.raw_material_in} out={lg.yield_out} | labor {_fmt_money(lg.labor_cost)}"
                        )
    except Exception as exc:
        return f"## Structured vault (PostgreSQL)\n_Database read failed: {type(exc).__name__}: {exc}_\n"

    text = "\n".join(lines).strip()
    if len(text) > max_chars:
        return text[: max_chars - 40] + "\n\n[... DB snapshot clipped ...]"
    return text
