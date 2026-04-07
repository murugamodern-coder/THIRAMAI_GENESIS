"""
Autonomous research routing: structural templates (energy / RE), fuzzy equity → deep financial, else detector.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from services.research_engine_templates import (
    RESEARCH_CATEGORY_DEEP_FINANCIAL,
    RESEARCH_CATEGORY_FINANCIAL_STOCKS,
    RESEARCH_CATEGORY_INDUSTRIAL_ENERGY,
    RESEARCH_CATEGORY_REAL_ESTATE,
    detect_research_business_category,
    structural_template_topic,
)
from services.stock_market_service import fetch_quote_yfinance, maybe_resolve_equity_for_topic


@dataclass(frozen=True)
class AutonomousResearchPlan:
    business_category: str
    user_message: str
    resolved_yahoo_symbol: str | None
    price_at_save: Decimal | None
    quote_currency: str | None
    equity_match_label: str | None


def _enrich_topic_with_quote(
    original: str,
    *,
    match_label: str,
    yahoo: str,
    price: Decimal | None,
    currency: str | None,
) -> str:
    lines = [
        "**LIVE MARKET SNAPSHOT** (machine-sourced via Yahoo Finance / optional Alpha Vantage; delayed; not advice):",
        f"- **Resolved listing:** {match_label}",
    ]
    if price is not None:
        lines.append(f"- **Approx. last price:** {price} {currency or 'INR'}")
    else:
        lines.append("- **Approx. last price:** unavailable (model should use filings / exchange data)")
    lines.append("")
    lines.append("**User topic (verbatim):**")
    lines.append(original.strip())
    return "\n".join(lines)


def plan_autonomous_research(topic: str) -> AutonomousResearchPlan:
    raw = (topic or "").strip()
    if not raw:
        return AutonomousResearchPlan(
            business_category=RESEARCH_CATEGORY_INDUSTRIAL_ENERGY,
            user_message=raw,
            resolved_yahoo_symbol=None,
            price_at_save=None,
            quote_currency=None,
            equity_match_label=None,
        )

    structural = structural_template_topic(raw)
    if structural == RESEARCH_CATEGORY_INDUSTRIAL_ENERGY:
        return AutonomousResearchPlan(
            business_category=RESEARCH_CATEGORY_INDUSTRIAL_ENERGY,
            user_message=raw,
            resolved_yahoo_symbol=None,
            price_at_save=None,
            quote_currency=None,
            equity_match_label=None,
        )
    if structural == RESEARCH_CATEGORY_REAL_ESTATE:
        return AutonomousResearchPlan(
            business_category=RESEARCH_CATEGORY_REAL_ESTATE,
            user_message=raw,
            resolved_yahoo_symbol=None,
            price_at_save=None,
            quote_currency=None,
            equity_match_label=None,
        )

    eq = maybe_resolve_equity_for_topic(raw)
    if eq and eq.get("yahoo"):
        yh = str(eq["yahoo"])
        label = str(eq.get("label") or yh)
        price, ccy = fetch_quote_yfinance(yh)
        msg = _enrich_topic_with_quote(raw, match_label=label, yahoo=yh, price=price, currency=ccy)
        return AutonomousResearchPlan(
            business_category=RESEARCH_CATEGORY_DEEP_FINANCIAL,
            user_message=msg,
            resolved_yahoo_symbol=yh,
            price_at_save=price,
            quote_currency=ccy,
            equity_match_label=label,
        )

    cat = detect_research_business_category(raw)
    if cat == RESEARCH_CATEGORY_FINANCIAL_STOCKS:
        return AutonomousResearchPlan(
            business_category=RESEARCH_CATEGORY_FINANCIAL_STOCKS,
            user_message=raw,
            resolved_yahoo_symbol=None,
            price_at_save=None,
            quote_currency=None,
            equity_match_label=None,
        )
    return AutonomousResearchPlan(
        business_category=cat,
        user_message=raw,
        resolved_yahoo_symbol=None,
        price_at_save=None,
        quote_currency=None,
        equity_match_label=None,
    )
