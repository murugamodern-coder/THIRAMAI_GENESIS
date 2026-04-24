"""
Negotiation intelligence: price bands, supplier comparison, tactics, and outreach templates
for real-world B2B / procurement conversations.
"""

from __future__ import annotations

import re
import statistics
from typing import Any, Literal

Role = Literal["buyer", "seller"]


def _f(x: float) -> float:
    return float(f"{x:.2f}")


def estimate_price_model(
    *,
    reference_unit_price: float,
    currency: str = "INR",
    market_volatility: Literal["low", "medium", "high"] = "medium",
    product_note: str = "",
) -> dict[str, Any]:
    """
    Derive market-average-style anchor, low/high band, and a fair value.

    `reference_unit_price` should be a recent quote, list price, or your last paid price.
    """
    if reference_unit_price <= 0:
        return {"ok": False, "error": "reference_unit_price must be positive"}
    sp = {
        "low": 0.10,
        "medium": 0.18,
        "high": 0.28,
    }.get(str(market_volatility).lower(), 0.18)
    t = re.sub(r"\s+", " ", (product_note or "")).lower()
    if any(k in t for k in ("commodity", "futures", "stainless", "copper", "steel")):
        sp = min(0.35, sp + 0.06)
    if any(k in t for k in ("bespoke", "custom tool", "die", "mould", "mold")):
        sp = min(0.4, sp + 0.08)
    ref = float(reference_unit_price)
    market_average = _f(ref)
    lo = _f(max(ref * (1.0 - sp), ref * 0.4))
    hi = _f(ref * (1.0 + sp))
    fair = _f((lo + hi) / 2.0 * (0.97 if market_volatility != "low" else 0.99))
    return {
        "ok": True,
        "currency": (currency or "INR")[:8].upper(),
        "market_average": market_average,
        "low_bound": min(lo, hi),
        "high_bound": max(lo, hi),
        "fair_price": fair,
        "assumptions": {
            "spread_percent": int(round(100 * sp, 0)),
            "note": "Bands are heuristics. Calibrate with invoices, LME, or 3+ vendor quotes when possible.",
        },
        "product_note": (product_note or "")[:2000],
    }


def _norm_buyer_prices(prices: list[float]) -> tuple[float, float]:
    pmin, pmax = min(prices), max(prices)
    return pmin, pmax if pmax > pmin else pmin + 1.0


def _score_for_buyer(unit: float, pmin: float, pmax: float) -> float:
    if pmax <= pmin:
        return 70.0
    t = 1.0 - (max(pmin, min(pmax, unit)) - pmin) / (pmax - pmin)
    return max(0.0, min(100.0, 100.0 * t))


def _score_delivery(days: float) -> float:
    d = max(0.0, float(days or 30.0))
    return max(0.0, min(100.0, 100.0 * (1.0 - min(d, 120.0) / 120.0)))


def compare_suppliers(
    suppliers: list[dict[str, Any]],
    *,
    role: Role = "buyer",
) -> dict[str, Any]:
    """
    Each supplier: name, unit_price, reliability_0_100 (optional, default 65),
    delivery_days (optional, default 21), optional notes, moq.
    """
    if not suppliers or len(suppliers) < 1:
        return {"ok": False, "error": "At least one supplier required"}
    clean: list[dict[str, Any]] = []
    for s in suppliers[:20]:
        name = str(s.get("name") or "Supplier").strip() or "Supplier"
        try:
            p = float(s.get("unit_price") or 0.0)
        except (TypeError, ValueError):
            p = 0.0
        if p <= 0:
            continue
        rel = float(s.get("reliability_0_100", s.get("reliability") or 65) or 65.0)
        rel = max(0.0, min(100.0, rel))
        days = float(s.get("delivery_days", s.get("lead_time_days") or 21) or 21.0)
        clean.append(
            {
                "name": name,
                "unit_price": p,
                "reliability_0_100": _f(rel),
                "delivery_days": int(days) if days == int(days) else days,
                "moq": s.get("moq"),
                "notes": str(s.get("notes", ""))[:500],
            }
        )
    if not clean:
        return {"ok": False, "error": "No valid rows with unit_price > 0"}
    prices = [c["unit_price"] for c in clean]
    pmin, pmax = _norm_buyer_prices(prices)
    ranked: list[dict[str, Any]] = []
    for c in clean:
        pr = c["unit_price"]
        s_price_buyer = _score_for_buyer(pr, pmin, pmax)
        s_price_seller = max(0.0, min(100.0, 100.0 * (pr - pmin) / (pmax - pmin) if pmax > pmin else 70.0))
        s_price = s_price_buyer if role == "buyer" else s_price_seller
        s_rel = float(c["reliability_0_100"])
        s_del = _score_delivery(float(c["delivery_days"]))
        composite = 0.45 * s_price + 0.32 * s_rel + 0.23 * s_del
        ranked.append(
            {
                **c,
                "scores": {
                    "price_score": _f(s_price),
                    "reliability": _f(s_rel),
                    "delivery_score": _f(s_del),
                    "composite": _f(composite),
                },
            }
        )
    ranked.sort(key=lambda x: float(x["scores"]["composite"]), reverse=True)
    for i, row in enumerate(ranked, 1):
        row["rank"] = i
    return {
        "ok": True,
        "role": role,
        "count": len(ranked),
        "suppliers": ranked,
        "price_context": {
            "min_quoted": _f(min(prices)),
            "max_quoted": _f(max(prices)),
            "median": _f(float(statistics.median(prices))),
        },
    }


def build_negotiation_suggestions(
    *,
    price_model: dict[str, Any],
    role: Role = "buyer",
    target_margin_buffer_pct: float = 5.0,
) -> dict[str, Any]:
    """Opening offer, walk-away, counter strategy from a prior `estimate_price_model` result."""
    if not price_model.get("ok"):
        return {"ok": False, "error": "Valid price_model required"}
    lo = float(price_model["low_bound"])
    hi = float(price_model["high_bound"])
    fair = float(price_model["fair_price"])
    mkt = float(price_model["market_average"])
    buf = max(0.0, min(20.0, float(target_margin_buffer_pct))) / 100.0
    if role == "buyer":
        opening = _f(fair * (1.0 - 0.06 - buf * 0.2))
        walk_away = _f(min(hi * 1.02, fair * 1.12))  # do not pay above
        walk_label = "Maximum you should agree (walk-away as buyer)"
        counter = [
            "Ask for line-item split (material, freight, GST) to pressure unit economics.",
            "Request MoQ / ladder pricing; tie the second PO to first shipment quality.",
            "If they anchor high, re-frame to fair band and your median of competing quotes (without disclosing if sensitive).",
        ]
    else:
        opening = _f(fair * (1.0 + 0.05 + buf * 0.15))
        walk_away = _f(max(lo * 0.98, fair * 0.9))
        walk_label = "Floor price — do not go below without executive sign-off"
        counter = [
            "Package value: warranty, SLAs, spares, or faster slots instead of only discount.",
            "Offer a modest cash-discount for advance / shorter credit period.",
            "If buyer pushes, split the move: half in price, half in service or volume commitment.",
        ]
    return {
        "ok": True,
        "role": role,
        "opening_offer": {"amount": opening, "hint": "Initial anchor; leave room to concede in steps."},
        "walk_away": {"amount": walk_away, "label": walk_label},
        "reference_points": {
            "fair_price": _f(fair),
            "market_average": _f(mkt),
            "low_bound": _f(lo),
            "high_bound": _f(hi),
        },
        "counter_strategy": counter,
    }


def generate_message_templates(
    *,
    product_line: str,
    supplier_name: str = "Supplier",
    your_company: str = "our firm",
    role: Role = "buyer",
    language: str = "en",
) -> dict[str, Any]:
    """Bilingual-friendly short templates for email / chat."""
    p = (product_line or "the agreed scope")[:500]
    sn = (supplier_name or "Team")[:120]
    en_open_buyer = (
        f"Subject: Commercial discussion — {p}\n\n"
        f"Dear {sn},\n"
        f"We are reviewing vendors for {p} for {your_company}. "
        f"Please share your best commercial offer (unit ex-works, freight, payment terms, lead time) "
        f"and any MoQ/price breaks. We compare like-for-like this week and will confirm by return."
    )
    en_counter_buyer = (
        f"Thanks for your quote. Our internal cross-check of specifications and lead time puts a fair range "
        f"slightly below your last number. We can move forward this week if you can meet us at [OPENING] "
        f"([currency]) ex [terms] with the delivery window we discussed."
    )
    en_walk_buyer = (
        f"Appreciate the work on your side. We cannot go beyond [WALK_AWAY] for this tranche; if that is not possible, "
        f"we may re-scope volume or park this for the next cycle."
    )
    en_open_seller = (
        f"Subject: Proposal — {p}\n\nHi,\n"
        f"Attaching our commercial structure for {p} with standard warranty and support. "
        f"We can refine MOQ, schedule, and payment in line with your run-rate."
    )
    en_counter_seller = (
        f"Thanks for your budget read. The fair structure for {p} holds at [OPENING] ([currency]) for the scope in our last mail. "
        f"If helpful, we can re-bundle warranty / delivery or split milestones—tell me the constraint to optimize."
    )
    en_walk_seller = (
        f"We want this to work, but we cannot go below [WALK_AWAY] for this build without re-scoping spec or lead time. "
        f"Happy to find a path if we align on that floor."
    )
    if str(language).lower().startswith("ta"):
        ta_line = (
            " (Tamil brief: வணக்கம் — விலை, delivery, payment terms அனுப்பவும். ஒப்பீடு செய்து இந்த வாரம் முடிவு சொல்வோம்.)"
        )
    else:
        ta_line = ""
    if role == "buyer":
        open_m, coun_m, walk_m = en_open_buyer, en_counter_buyer, en_walk_buyer
    else:
        open_m, coun_m, walk_m = en_open_seller, en_counter_seller, en_walk_seller
    return {
        "ok": True,
        "product_line": p,
        "language": "en" if not str(language).lower().startswith("ta") else "en+ta",
        "email_opening": open_m,
        "email_counter": coun_m,
        "email_walk_away": walk_m,
        "tamil_cue": ta_line.strip() if ta_line else None,
    }


def generate_negotiation_script(
    *,
    product_line: str,
    role: Role = "buyer",
    your_company: str = "us",
) -> dict[str, Any]:
    """Structured call/meeting script outline."""
    pl = (product_line or "the scope")[:500]
    if role == "buyer":
        phases = [
            {
                "phase": "open",
                "objective": "Rapport + restate need + timeline",
                "says": f"Thanks for joining. We are standardizing {pl} for {your_company} with a target decision this month. I want to align on spec, lead time, and TCO first.",
                "listen_for": "Hidden fees, MOQ, allocation risk, FX exposure.",
            },
            {
                "phase": "anchor",
                "objective": "Set fair band without unnecessary aggression",
                "says": "Our model puts the fair value in a range around [FAIR/OPENING]. Help me understand the gap versus your list.",
                "asks": "What moves the number without hurting quality or delivery?",
            },
            {
                "phase": "close_or_exit",
                "objective": "Get commitment or a dated counter",
                "says": "If you can do [X] on unit price and [Y] on delivery with written terms, we can issue the PO. Otherwise we will pause and revisit next quarter.",
            },
        ]
    else:
        phases = [
            {
                "phase": "open",
                "objective": "Credibility + scope + value levers",
                "says": f"Thanks for the context on {pl}. I will walk our standard build, inclusions, and the levers that move price and lead time for {your_company}.",
                "asks": "What is driving the timeline and budget on your side?",
            },
            {
                "phase": "anchor",
                "objective": "Defend value; trade discount for terms",
                "says": "The fair number for the agreed scope is around [FAIR/OPENING]. I can work with you on payment or milestones if the spec stays stable.",
            },
            {
                "phase": "close_or_exit",
                "objective": "Written go-ahead or dated next step",
                "says": "If you can confirm the PO on these terms, we lock capacity. Otherwise I need a counter by [date] to reallocate the slot.",
            },
        ]
    return {"ok": True, "product_line": pl, "phases": phases, "role": role}


def full_negotiation_pack(
    *,
    product_line: str,
    reference_unit_price: float,
    currency: str = "INR",
    market_volatility: str = "medium",
    suppliers: list[dict[str, Any]] | None,
    role: Role = "buyer",
    your_company: str = "our team",
) -> dict[str, Any]:
    """Convenience: one call returning estimate, optional comparison, tactics, and templates."""
    pe = estimate_price_model(
        reference_unit_price=reference_unit_price,
        currency=currency,
        market_volatility=market_volatility,  # type: ignore[arg-type]
        product_note=product_line,
    )
    comp = None
    if suppliers and len(suppliers) >= 1:
        comp = compare_suppliers(suppliers, role=role)
    neg = build_negotiation_suggestions(price_model=pe, role=role, target_margin_buffer_pct=5.0)
    tmpl = generate_message_templates(
        product_line=product_line, supplier_name="[Supplier]", your_company=your_company, role=role
    )
    script = generate_negotiation_script(product_line=product_line, role=role, your_company=your_company)
    if neg.get("ok") and pe.get("ok") and "opening_offer" in neg:
        oa = str(neg["opening_offer"].get("amount", ""))
        w = str(neg.get("walk_away", {}).get("amount", ""))
        fair = str(pe.get("fair_price", "")) if pe.get("ok") else ""
        for k, v in list(tmpl.items()):
            if not isinstance(v, str):
                continue
            s = v.replace("[currency]", str(currency)).replace("[OPENING]", oa).replace("[WALK_AWAY]", w)
            if fair and "[FAIR" in s:
                s = s.replace("[FAIR/OPENING]", f"{fair} (fair) / {oa} (opening)")
            tmpl[k] = s
    return {
        "ok": True,
        "product_line": (product_line or "")[:2000],
        "price_model": pe,
        "supplier_comparison": comp,
        "negotiation": neg,
        "templates": tmpl,
        "script": script,
    }


def enrich_with_market_research(
    product_line: str,
    *,
    max_results: int = 10,
) -> dict[str, Any]:
    """Optional web/supplier research context; safe to call when TAVILy/search is configured."""
    try:
        from services.research_engine_service import run_supplier_research_sync
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": str(exc), "enrichment": None}
    q = f"{(product_line or 'procurement')[:500]} market price terms MOQ"
    r = run_supplier_research_sync(str(q)[:500], max_results=int(max_results))
    if not r.get("ok"):
        return {**r, "enrichment": "research_failed", "assumption": "Use your own 3+ quotes to calibrate bands."}
    return {
        "ok": True,
        "enrichment": "ok",
        "summary": (r.get("summary") or "")[:4000],
        "supplier_hints": (r.get("suppliers") or [])[:20],
        "pricing_notes": (r.get("estimated_pricing") or r.get("pricing_notes") or [])[:20],
    }
