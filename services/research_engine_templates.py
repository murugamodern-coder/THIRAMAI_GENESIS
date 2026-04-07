"""
Research Hub: business-category templates (Industrial/Energy, Financial/Stocks, Real Estate).

Auto-detection picks a template from the topic; callers may override via API.
"""

from __future__ import annotations

import re
from typing import Final

# API / DB values
RESEARCH_CATEGORY_INDUSTRIAL_ENERGY: Final = "industrial_energy"
RESEARCH_CATEGORY_FINANCIAL_STOCKS: Final = "financial_stocks"
RESEARCH_CATEGORY_REAL_ESTATE: Final = "real_estate"
RESEARCH_CATEGORY_DEEP_FINANCIAL: Final = "deep_financial"

VALID_RESEARCH_CATEGORIES: Final[tuple[str, ...]] = (
    RESEARCH_CATEGORY_INDUSTRIAL_ENERGY,
    RESEARCH_CATEGORY_FINANCIAL_STOCKS,
    RESEARCH_CATEGORY_REAL_ESTATE,
    RESEARCH_CATEGORY_DEEP_FINANCIAL,
)


def structural_template_topic(topic: str) -> str | None:
    """
    Return ``industrial_energy`` or ``real_estate`` when the topic is structurally that domain.

    ``None`` means the router may try **fuzzy equity** (company names) or fall back to financial / industrial.
    """
    raw = (topic or "").strip()
    t = f" {raw.lower()} "

    energy_needles = (
        " solar ",
        "photovoltaic",
        " pv ",
        " pv-",
        "wind farm",
        "wind power",
        "renewable energy",
        "open access",
        "rooftop",
        "ground mount",
        "ground-mount",
        "megawatt",
        "cuf",
        "power purchase",
        " ppa ",
        "evacuation",
        "mnre",
        "ntpc green",
        "adani green",
        "renew power",
        "reits solar",
    )
    if re.search(r"\b\d+\s*mw\b", raw.lower()) or any(n in t for n in energy_needles):
        return RESEARCH_CATEGORY_INDUSTRIAL_ENERGY

    re_needles = (
        "guideline value",
        "registration cost",
        "registration fee",
        "stamp duty",
        "sq.ft",
        "sq ft",
        "sqft",
        "square feet",
        "square foot",
        "carpet area",
        "built-up",
        "mandakolathur",
        "sale deed",
        "parent deed",
        " encumbrance",
        "cmda",
        "dtcp",
        "rera ",
        "land register",
        "sub-registrar",
        "sub registrar",
        "plot in ",
        "plot at ",
        "survey number",
        "patta ",
        "chitta ",
    )
    if any(n in t for n in re_needles):
        return RESEARCH_CATEGORY_REAL_ESTATE
    if "acre" in t and ("land" in t or "plot" in t or "agricultural" in t):
        return RESEARCH_CATEGORY_REAL_ESTATE

    return None


def detect_research_business_category(topic: str) -> str:
    """
    Classify a free-text topic into a research template (excludes ``deep_financial`` — that is autonomy-only).

    - Structural **energy** / **real estate** first.
    - **Financial** keywords → ``financial_stocks``.
    - Default → ``industrial_energy`` (legacy DPR-style).
    """
    raw = (topic or "").strip()
    s = structural_template_topic(raw)
    if s is not None:
        return s

    t = f" {raw.lower()} "

    financial_needles = (
        "vodafone idea",
        "vodafone",
        "nse:",
        "bse:",
        "sensex",
        "nifty",
        " stock",
        "stocks",
        "equity",
        "share price",
        "q1 fy",
        "q2 fy",
        "q3 fy",
        "q4 fy",
        "pe ratio",
        "p/e",
        "p/e ratio",
        "dividend yield",
        "market cap",
        "arpu",
        " eps ",
        "ebitda margin",
        "promoter holding",
        "fii ",
        "dii ",
        "mutual fund",
        "portfolio",
        "nifty 50",
        "bank nifty",
        "earnings call",
        "concall",
        "scrip",
        "demat",
    )
    if any(n in t for n in financial_needles):
        return RESEARCH_CATEGORY_FINANCIAL_STOCKS

    return RESEARCH_CATEGORY_INDUSTRIAL_ENERGY


def industrial_energy_skeleton() -> str:
    return (
        "You are a **principal consultant** drafting a bankable-style **Detailed Project Report (DPR)** "
        "and market memo for an Indian **industrial / renewable energy** developer.\n\n"
        "Output **professional Markdown** only.\n\n"
        "**Required sections** (use `##` headings exactly as named):\n\n"
        "## Executive Summary\n"
        "Purpose, scale (**MW**), geography, **land (acres)** footprint, **ROI / payback** thesis, "
        "key risks, and a clear **go / no-go** headline.\n\n"
        "## Technical Specifications\n"
        "Technology stack (modules/inverters), grid/evacuation, CUF, degradation, O&M, land use — "
        "apply **GLOBAL TRUTHS** for CAPEX-per-MW and acres/MW unless the user topic overrides.\n\n"
        "## 15-Year Cash Flow\n"
        "A **Markdown table** for **15 operating years** (years 1–15): **Generation (MU)**, "
        "**Tariff / revenue**, **O&M**, **EBITDA**, **Debt service** (if leveraged), **Net cash**. "
        "Anchor **initial capex** with **GLOBAL TRUTHS**; show **ROI** narrative.\n\n"
        "## Risk Mitigation\n"
        "Permitting, grid/curtailment, PPA/counterparty, construction, resource, policy, mitigations.\n\n"
        "## Sources, Assumptions & Next Steps\n"
        "Cite source categories; flag data gaps.\n\n"
        "Use bullets and `###` subsections. For uncertain figures, show **low / base / high** scenarios."
    )


def financial_stocks_skeleton() -> str:
    return (
        "You are an **equity research analyst** producing a concise **India markets** memo on the "
        "user's topic (listed company, sector, or stock).\n\n"
        "Output **professional Markdown** only.\n\n"
        "**FORBIDDEN in this report:** solar plant DPR content, **MW / acre/MW**, **solar CAPEX per MW**, "
        "CUF for PV, PPA solar economics, or renewable **project ROI** unless the user explicitly asks for "
        "that angle in the topic. This template is **Financial / Stocks**, not energy infrastructure.\n\n"
        "**Required sections** (use `##` headings exactly as named):\n\n"
        "## Executive Summary\n"
        "Investment view, key drivers, and top risks (1 short paragraph + bullets).\n\n"
        "## Company / Sector Snapshot\n"
        "Business model, geography, competitive position, recent developments.\n\n"
        "## Valuation & KPIs\n"
        "Include a **Markdown table** of the main metrics, with rows such as: "
        "**P/E (TTM or forward as available)**, **Market cap** (INR / USD as appropriate), "
        "**Dividend yield** (if relevant), and **ARPU** (for telecom / subscription businesses — "
        "state N/A clearly if not applicable). Add **EPS trend** or revenue growth if useful.\n\n"
        "## Risks & Catalysts\n"
        "Regulatory, balance sheet, competition, execution; upcoming catalysts.\n\n"
        "## Sources, Assumptions & Next Steps\n"
        "Disclose that figures may be delayed vs exchange filings; list diligence items.\n\n"
        "Use bullets and `###` subsections. Label estimates vs reported data."
    )


def deep_financial_analysis_skeleton() -> str:
    return (
        "You are a **senior sell-side / buyside analyst** producing a **Deep Financial Analysis** for an "
        "**Indian listed equity** (NSE/BSE). The user message may include a **machine-resolved ticker** and "
        "a **live price hint** — treat price as **indicative / delayed**, validate against exchange filings.\n\n"
        "Output **professional Markdown** only.\n\n"
        "**FORBIDDEN:** generic solar DPR / **MW / acre-MW** project templates unless the company is explicitly "
        "a pure-play developer **and** the user asked for project economics.\n\n"
        "**Required sections** (use `##` headings exactly as named):\n\n"
        "## Executive Summary\n"
        "Thesis, key numbers, top risks, and time horizon.\n\n"
        "## Balance Sheet Analysis\n"
        "Capital structure, leverage (Net debt/EBITDA or interest coverage if inferable), working capital cycle, "
        "contingent liabilities, and asset quality. Use a **Markdown table** for key line items (latest annual / "
        "TTM as available).\n\n"
        "## Cash Flow Analysis\n"
        "Operating vs investing vs financing cash flows, **capex intensity**, **free cash flow** trend, "
        "dividend / buyback capacity. Flag red flags (negative CFO, rising receivables, etc.).\n\n"
        "## Technical Analysis\n"
        "Price trend (52-week / multi-month), major **moving averages** (50/200-day narrative), **volume** "
        "context, and classic indicators (**RSI**, **MACD**) where you can infer from public chart summaries — "
        "if data is missing, state **data gap** and suggest what to pull from a charting terminal.\n\n"
        "## Valuation & Peers\n"
        "P/E, P/B, EV/EBITDA, **market cap**, **dividend yield**, and **ARPU** only if business-relevant (else N/A). "
        "Peer table (2–4 comps).\n\n"
        "## Risks, Catalysts & Next Steps\n"
        "Regulatory, commodity, execution, governance; upcoming events.\n\n"
        "## Sources & Disclaimer\n"
        "Not investment advice; cite filing types (annual report, exchange announcement).\n\n"
        "Use bullets and `###` subsections."
    )


def real_estate_skeleton() -> str:
    return (
        "You are a **real estate / land transaction** advisor drafting a structured brief for **Indian** "
        "residential, commercial, or **agricultural land** deals (e.g. registration workflows similar to "
        "**Mandakolathur**-style land tasks when the topic implies Tamil Nadu / local parcels).\n\n"
        "Output **professional Markdown** only.\n\n"
        "**FORBIDDEN unless the user topic explicitly asks:** utility-scale **solar MW** economics, "
        "**acres per MW**, solar **CUF**, or solar **PPA** — this template is **Real Estate**, not energy plants.\n\n"
        "**Required sections** (use `##` headings exactly as named):\n\n"
        "## Executive Summary\n"
        "What is being evaluated, location context, and recommended next legal/diligence steps.\n\n"
        "## Property / Land Snapshot\n"
        "Parcel type, boundaries/survey references if mentioned, zoning / use, possession status.\n\n"
        "## Area & Value Economics\n"
        "Include a **Markdown table** with rows for: **Built-up / land area (Sq.Ft or grounds/sq.m with conversion)** "
        "**, **Guideline value / guidance rate** (circle/sub-registrar context), and **Registration costs** "
        "(stamp duty, registration fee, and other charges — use **percentage + illustrative INR** where "
        "exact rates vary by state; flag TN vs generic India if unclear).\n\n"
        "## Legal & Compliance Checklist\n"
        "Title flow, encumbrance, EC, mutation, tax receipts, power of attorney risks.\n\n"
        "## Sources, Assumptions & Next Steps\n"
        "Note that guideline values are state/circle specific; recommend official sub-registrar verification.\n\n"
        "Use bullets and `###` subsections."
    )


def category_label(category: str) -> str:
    return {
        RESEARCH_CATEGORY_INDUSTRIAL_ENERGY: "Industrial / Energy",
        RESEARCH_CATEGORY_FINANCIAL_STOCKS: "Financial / Stocks",
        RESEARCH_CATEGORY_REAL_ESTATE: "Real Estate",
        RESEARCH_CATEGORY_DEEP_FINANCIAL: "Deep Financial Analysis",
    }.get(category, category)
