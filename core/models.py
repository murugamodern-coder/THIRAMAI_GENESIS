"""
Domain DTOs (Pydantic). SQL tables / ORM: see `db/schema.sql` and `core/db/models.py`.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class User(BaseModel):
    """Sovereign operator profile (future users table)."""

    id: UUID | None = None
    display_name: str = ""
    locale: str = "en-IN"
    timezone: str = "Asia/Kolkata"
    health_goals_json: dict[str, Any] = Field(default_factory=dict)
    blockers_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DebtKind(str, Enum):
    TERM_LOAN = "term_loan"
    WORKING_CAPITAL = "working_capital"
    CREDIT_CARD = "credit_card"
    PAYABLE = "payable"
    OTHER = "other"


class Debt(BaseModel):
    """Liability line (future debts table)."""

    id: UUID | None = None
    user_id: UUID | None = None
    name: str
    kind: DebtKind = DebtKind.OTHER
    principal_inr: Decimal = Decimal("0")
    apr_percent: Decimal | None = None
    due_date: date | None = None
    notes: str = ""
    meta_json: dict[str, Any] = Field(default_factory=dict)


class AssetKind(str, Enum):
    CASH = "cash"
    INVENTORY = "inventory"
    EQUIPMENT = "equipment"
    REAL_ESTATE = "real_estate"
    RECEIVABLE = "receivable"
    IP = "ip"
    OTHER = "other"


class Asset(BaseModel):
    """Balance-sheet style asset (future assets table)."""

    id: UUID | None = None
    user_id: UUID | None = None
    name: str
    kind: AssetKind = AssetKind.OTHER
    value_inr: Decimal | None = None
    quantity: Decimal | None = None
    unit: str = ""
    acquired_at: date | None = None
    notes: str = ""
    meta_json: dict[str, Any] = Field(default_factory=dict)
