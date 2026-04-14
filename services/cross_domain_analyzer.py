"""
Cross-domain intelligence: personal finance + multi-org business + equity portfolio.

Produces ranked insights, risk cascade hints, and a short \"Captain\" line for Today brief / Jarvis.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.database import get_session_factory
from core.db.models import Organization, PersonalLoan, ResearchDocument, UserOrganizationMembership
from services.economics_service import get_business_margin
from services.membership_service import list_memberships_for_user
from services.portfolio_service import daily_equity_pnl_inr_sync, get_portfolio_summary_sync


def _dec(v: Any) -> Decimal:
    try:
        return Decimal(str(v or 0)).quantize(Decimal("0.01"))
    except Exception:
        return Decimal("0.00")


def _fmt_inr_compact(d: Decimal) -> str:
    n = int(d.quantize(Decimal("1")))
    return f"₹{n:,}"


def _active_org_ids(session: Session, user_id: int) -> list[int]:
    uid = int(user_id)
    out: list[int] = []
    for m in list_memberships_for_user(session, uid):
        if not getattr(m, "is_active", True):
            continue
        oid = int(m.organization_id)
        org = session.get(Organization, oid)
        if org is None or getattr(org, "is_disabled", False):
            continue
        out.append(oid)
    return sorted(set(out))


def _total_monthly_emi(session: Session, user_id: int) -> Decimal:
    rows = session.scalars(
        select(PersonalLoan.emi_amount).where(
            PersonalLoan.user_id == int(user_id),
            PersonalLoan.is_closed.is_(False),
            PersonalLoan.emi_amount.isnot(None),
        )
    ).all()
    t = Decimal("0")
    for r in rows:
        if r is not None:
            t += _dec(r)
    return t.quantize(Decimal("0.01"))


def _research_recent_count(session: Session, user_id: int, days: int = 7) -> int:
    since = datetime.now(timezone.utc) - timedelta(days=int(days))
    return int(
        session.execute(
            select(func.count())
            .select_from(ResearchDocument)
            .where(ResearchDocument.user_id == int(user_id), ResearchDocument.created_at >= since)
        ).scalar()
        or 0
    )


def _monthly_income_proxy(session: Session, user_id: int, org_margins: list[dict[str, Any]]) -> Decimal:
    raw = (os.getenv("THIRAMAI_CROSS_DOMAIN_MONTHLY_INCOME_INR") or "").strip()
    if raw:
        try:
            v = _dec(raw)
            if v > 0:
                return v
        except Exception:
            pass
    pos_net = Decimal("0")
    for m in org_margins:
        if not m.get("ok"):
            continue
        npv = _dec(m.get("net_profit_inr"))
        if npv > 0:
            pos_net += npv
    if pos_net > 0:
        return pos_net.quantize(Decimal("0.01"))
    rev_sum = Decimal("0")
    for m in org_margins:
        if not m.get("ok"):
            continue
        rev_sum += _dec(m.get("revenue_inr"))
    if rev_sum > 0:
        return (rev_sum * Decimal("0.15")).quantize(Decimal("0.01"))
    return Decimal("0")


def _insight_score(
    *,
    financial_impact: int,
    urgency: int,
    dependencies: int,
) -> float:
    return financial_impact * 0.45 + urgency * 0.4 + dependencies * 0.15


def _rank_insights(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for x in raw:
        x["score"] = round(
            _insight_score(
                financial_impact=int(x.get("financial_impact") or 0),
                urgency=int(x.get("urgency") or 0),
                dependencies=int(x.get("dependencies") or 0),
            ),
            2,
        )
    raw.sort(key=lambda z: float(z.get("score") or 0), reverse=True)
    return raw[:3]


def analyze_cross_domain(
    user_id: int,
    *,
    organization_id: int = 0,
    financial_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Aggregate personal cash signals, all active org P&L margins, and equity P&L.

    ``financial_snapshot`` avoids a duplicate morning brief when callers already have it.
    ``THIRAMAI_CROSS_DOMAIN_MONTHLY_INCOME_INR`` sets assumed household income when business nets are zero.
    """
    uid = int(user_id)
    if uid <= 0:
        return {
            "ok": False,
            "error": "invalid user",
            "captain_message": "",
            "top_insights": [],
            "risk_alerts": [],
            "recommendations": [],
            "metrics": {},
        }

    factory = get_session_factory()
    if factory is None:
        return {
            "ok": False,
            "error": "database not configured",
            "captain_message": "",
            "top_insights": [],
            "risk_alerts": [],
            "recommendations": [],
            "metrics": {},
        }

    if financial_snapshot is None:
        from services.personal_command_center_service import build_morning_brief_sync

        oid_fb = int(organization_id) if int(organization_id) > 0 else 0
        brief = build_morning_brief_sync(user_id=uid, organization_id=oid_fb, fernet=None)
        financial_snapshot = brief.get("financial_snapshot") if isinstance(brief.get("financial_snapshot"), dict) else {}

    fin = financial_snapshot or {}
    spent_month = _dec(fin.get("spent_month"))
    spent_today = _dec(fin.get("spent_today"))
    upcoming = fin.get("upcoming_emis") if isinstance(fin.get("upcoming_emis"), list) else []

    org_margins: list[dict[str, Any]] = []
    monthly_income = Decimal("0")
    with factory() as session:
        org_ids = _active_org_ids(session, uid)
        total_emi = _total_monthly_emi(session, uid)
        research_n = _research_recent_count(session, uid, days=7)
        for oid in org_ids:
            row = get_business_margin(oid)
            name = ""
            o = session.get(Organization, oid)
            if o is not None:
                name = (o.name or "").strip() or f"Org {oid}"
            org_margins.append({**row, "org_name": name})
        monthly_income = _monthly_income_proxy(session, uid, org_margins)

    total_business_opex = sum(_dec(m.get("operational_expenses_inr")) for m in org_margins if m.get("ok"))
    daily_pnl = daily_equity_pnl_inr_sync(uid)
    stock_loss = max(Decimal("0"), (-daily_pnl).quantize(Decimal("0.01")))
    port = get_portfolio_summary_sync(uid)
    total_pnl_port = _dec(port.get("total_pnl_inr")) if port.get("ok") else Decimal("0")

    outflows = total_emi + spent_month + total_business_opex + stock_loss
    available_cash = (monthly_income - outflows).quantize(Decimal("0.01"))

    insights: list[dict[str, Any]] = []
    risk_alerts: list[str] = []
    recommendations: list[str] = []

    if monthly_income <= 0 and (total_emi > 0 or spent_month > 0 or total_business_opex > 0):
        recommendations.append(
            "Set THIRAMAI_CROSS_DOMAIN_MONTHLY_INCOME_INR (or grow business net) so cash runway is measurable."
        )

    if available_cash < 0:
        crisis = (
            f"Cash crisis detected: outflow {_fmt_inr_compact(outflows)} > income proxy {_fmt_inr_compact(monthly_income)}. "
            "Risk: EMI delay likely."
        )
        insights.append(
            {
                "id": "cash_crisis",
                "title": "Cash crisis",
                "detail": crisis,
                "category": "finance",
                "financial_impact": 95,
                "urgency": 92,
                "dependencies": 70,
            }
        )
        risk_alerts.append(crisis)
        recommendations.extend(
            [
                "Pause discretionary trading until cash stabilizes.",
                "Collect unpaid invoices and chase largest debtors first.",
            ]
        )

    margin_rows = [
        m
        for m in org_margins
        if m.get("ok") and m.get("gross_margin_pct") is not None and (m.get("org_name") or str(m.get("organization_id")))
    ]
    if len(margin_rows) >= 2:
        by_margin = sorted(margin_rows, key=lambda x: float(x.get("gross_margin_pct") or 0))
        worst, best = by_margin[0], by_margin[-1]
        wb = float(worst.get("gross_margin_pct") or 0)
        bb = float(best.get("gross_margin_pct") or 0)
        if bb - wb >= 5:
            wn = str(worst.get("org_name") or "Business B")
            bn = str(best.get("org_name") or "Business A")
            detail = f"{bn} margin ~{bb:.0f}%. {wn} margin ~{wb:.0f}%. Shift focus or resources toward the stronger unit."
            insights.append(
                {
                    "id": "business_spread",
                    "title": "Business performance spread",
                    "detail": detail,
                    "category": "business",
                    "financial_impact": 55,
                    "urgency": 40,
                    "dependencies": 35,
                }
            )

    emi_soon = False
    today_d = datetime.now(timezone.utc).date()
    for emi in upcoming:
        if not isinstance(emi, dict):
            continue
        due_s = emi.get("due")
        if not due_s:
            continue
        try:
            due_d = date.fromisoformat(str(due_s)[:10])
            if 0 <= (due_d - today_d).days <= 7:
                emi_soon = True
                break
        except Exception:
            continue

    weak_business = any(m.get("ok") and _dec(m.get("net_profit_inr")) < 0 for m in org_margins)
    chain = stock_loss > Decimal("500") and emi_soon and (spent_month > monthly_income * Decimal("0.2") or weak_business)
    if chain:
        msg = "Chain risk detected: equity draw / spend pressure may tighten cash before EMI — watch business stress."
        insights.append(
            {
                "id": "risk_cascade",
                "title": "Risk cascade",
                "detail": msg,
                "category": "risk",
                "financial_impact": 80,
                "urgency": 78,
                "dependencies": 85,
            }
        )
        risk_alerts.append(msg)

    if research_n >= 1 and total_pnl_port < Decimal("-2000") and port.get("ok") and (port.get("positions") or []):
        opp = (
            "Opportunity: fresh research on file, equity is below cost on the book — "
            "consider aligning production or procurement with the research thesis (not financial advice)."
        )
        insights.append(
            {
                "id": "opportunity_stack",
                "title": "Stacked opportunity signal",
                "detail": opp,
                "category": "opportunity",
                "financial_impact": 45,
                "urgency": 35,
                "dependencies": 50,
            }
        )

    daily_spend_hint = spent_today if spent_today > 0 else Decimal("0")
    if daily_spend_hint <= 0 and spent_month > 0:
        dom = max(1, int(today_d.day))
        daily_spend_hint = (spent_month / Decimal(str(dom))).quantize(Decimal("0.01"))
    if daily_spend_hint <= 0:
        daily_spend_hint = Decimal("1")

    captain_parts: list[str] = []
    if stock_loss > 0 and daily_spend_hint > 0:
        days_eq = float((stock_loss / daily_spend_hint).quantize(Decimal("0.01")))
        if days_eq >= 0.3:
            captain_parts.append(
                f"Captain, your stock loss today is about {days_eq:.1f} day(s) of typical personal spend."
            )
    if available_cash < 0:
        captain_parts.append(
            f"Cash is negative on the monthly proxy by {_fmt_inr_compact(-available_cash)} — freeze discretionary trades and collect receivables first."
        )
    elif margin_rows and len(margin_rows) >= 2:
        by_margin = sorted(margin_rows, key=lambda x: float(x.get("gross_margin_pct") or 0))
        if float(by_margin[-1].get("gross_margin_pct") or 0) - float(by_margin[0].get("gross_margin_pct") or 0) >= 8:
            captain_parts.append(
                f"Focus energy on {by_margin[-1].get('org_name') or 'your strongest business'}; it is carrying margin leadership."
            )

    if not captain_parts:
        if insights:
            captain_parts.append(str(insights[0].get("detail") or insights[0].get("title") or "Review cross-domain signals."))
        else:
            captain_parts.append("Systems look balanced across personal, business, and equity — stay the course.")

    captain_message = " ".join(captain_parts).strip()

    top_insights = _rank_insights(insights)

    return {
        "ok": True,
        "captain_message": captain_message,
        "top_insights": top_insights,
        "risk_alerts": risk_alerts[:6],
        "recommendations": recommendations[:8],
        "metrics": {
            "total_emi_inr": str(total_emi),
            "total_business_expense_inr": str(total_business_opex),
            "stock_loss_inr": str(stock_loss),
            "monthly_income_proxy_inr": str(monthly_income),
            "personal_spent_month_inr": str(spent_month),
            "available_cash_proxy_inr": str(available_cash),
            "daily_equity_realized_pnl_inr": str(daily_pnl),
        },
        "organizations_compared": [
            {
                "organization_id": m.get("organization_id"),
                "name": m.get("org_name"),
                "gross_margin_pct": m.get("gross_margin_pct"),
                "net_profit_inr": m.get("net_profit_inr"),
            }
            for m in org_margins
            if m.get("ok")
        ],
        "chain_risk": bool(chain),
    }


__all__ = ["analyze_cross_domain"]
