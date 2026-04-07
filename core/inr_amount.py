"""Parse informal INR amounts (e.g. ₹4L, 2.5 lakh, 1.5Cr) into Decimal rupees."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any


def parse_inr_amount(raw: Any) -> Decimal | None:
    """
    Accept numeric types, digit strings, or shorthand (L/lakh, K, Cr/crore).
    Returns rupees as Decimal, or None if unparseable.
    """
    if raw is None:
        return None
    if isinstance(raw, Decimal):
        return raw
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        try:
            return Decimal(str(raw))
        except InvalidOperation:
            return None

    s = str(raw).strip()
    if not s:
        return None

    s = (
        s.replace(",", "")
        .replace("₹", "")
        .replace("Rs.", "")
        .replace("Rs", "")
        .replace("INR", "")
        .replace("inr", "")
        .strip()
    )
    low = s.lower().replace(" ", "")

    mult = Decimal(1)
    num_part = low

    if "crore" in low or re.search(r"[0-9.]+cr\b", low):
        m = re.search(r"([0-9]*\.?[0-9]+)\s*cr", low)
        if m:
            num_part = m.group(1)
        mult = Decimal("10000000")
    elif "lakh" in low or re.search(r"[0-9.]+l\b", low):
        m = re.search(r"([0-9]*\.?[0-9]+)\s*l(?:akh)?", low)
        if m:
            num_part = m.group(1)
        mult = Decimal("100000")
    elif re.search(r"[0-9.]+k\b", low):
        m = re.search(r"([0-9]*\.?[0-9]+)\s*k", low)
        if m:
            num_part = m.group(1)
        mult = Decimal("1000")

    num_part = re.sub(r"[^0-9.+-]", "", num_part)
    if not num_part or num_part in (".", "+", "-"):
        return None
    try:
        return Decimal(num_part) * mult
    except InvalidOperation:
        return None


def parse_percent(raw: Any) -> float | None:
    """
    Parse values like 26, "26%", "24.5%", " 28 " into a float annual percentage.
    Returns None if unparseable.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    s = str(raw).strip().replace("%", "").replace(",", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None
