"""SQLAlchemy ORM for THIRAMAI V2.1 — see db/db_schema.sql."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, Integer, JSON, LargeBinary, Numeric, PrimaryKeyConstraint, SmallInteger, String, Text, UniqueConstraint, func
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db.base import Base


class AssetStatusEnum(str, enum.Enum):
    active = "active"
    archived = "archived"
    pending = "pending"


class DebtCategoryEnum(str, enum.Enum):
    term_loan = "term_loan"
    working_capital = "working_capital"
    credit_card = "credit_card"
    payable = "payable"
    other = "other"


class Organization(Base):
    """
    Tenant / company (Identity & Access roadmap: id, name, plan, created_at).

    Extra columns (gst_number, industry) remain for legacy vault migration and ERP context.
    """

    __tablename__ = "organizations"

    # Integer on SQLite so autoincrement works in dev/tests; BigInteger on PostgreSQL.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    gst_number: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    plan: Mapped[str] = mapped_column(Text, nullable=False, server_default="free", default="free")
    is_disabled: Mapped[bool] = mapped_column(default=False, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    assets: Mapped[list["Asset"]] = relationship(back_populates="organization")
    memberships: Mapped[list["UserOrganizationMembership"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    roles: Mapped[list["Role"]] = relationship(back_populates="organization")
    approvals: Mapped[list["Approval"]] = relationship(back_populates="organization")
    learning_logs: Mapped[list["LearningLog"]] = relationship(back_populates="organization")
    system_audit_logs: Mapped[list["SystemAuditLog"]] = relationship(back_populates="organization")
    debts: Mapped[list["Debt"]] = relationship(back_populates="organization")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="organization")
    bills: Mapped[list["Bill"]] = relationship(back_populates="organization")
    departments: Mapped[list["Department"]] = relationship(back_populates="organization")
    staff_profiles: Mapped[list["StaffProfile"]] = relationship(back_populates="organization")
    operational_expenses: Mapped[list["OperationalExpense"]] = relationship(back_populates="organization")
    compliance_cases: Mapped[list["ComplianceCase"]] = relationship(back_populates="organization")
    comms_inbox: Mapped[list["CommsInbox"]] = relationship(back_populates="organization")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="organization")
    factory_billing_hold_row: Mapped[Optional["FactoryBillingHold"]] = relationship(
        back_populates="organization", uselist=False
    )
    factory_projects: Mapped[list["ProjectStage"]] = relationship(back_populates="organization")
    equipment: Mapped[list["Equipment"]] = relationship(back_populates="organization")
    ledger_transactions: Mapped[list["LedgerTransaction"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    personal_suggestion_feedback: Mapped[list["PersonalSuggestionFeedback"]] = relationship(
        back_populates="organization"
    )
    inventory_items_v2: Mapped[list["InventoryItem"]] = relationship(back_populates="organization")
    suppliers: Mapped[list["Supplier"]] = relationship(back_populates="organization")
    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(back_populates="organization")
    gst_records: Mapped[list["GstRecord"]] = relationship(back_populates="organization")
    raw_materials: Mapped[list["RawMaterial"]] = relationship(back_populates="organization")
    ai_decisions: Mapped[list["AiDecision"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    usage_logs: Mapped[list["UsageLog"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    control_plane_alerts: Mapped[list["ControlPlaneAlert"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    control_plane_jobs: Mapped[list["ControlPlaneJob"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    personal_meetings: Mapped[list["PersonalMeeting"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    agro_subsidy_cases: Mapped[list["AgroSubsidyCase"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    business_tasks: Mapped[list["BusinessTask"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    supplier_payments: Mapped[list["SupplierPayment"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    liquidity_row: Mapped[Optional["OrganizationLiquidity"]] = relationship(
        back_populates="organization", uselist=False
    )
    research_documents: Mapped[list["ResearchDocument"]] = relationship(back_populates="organization")
    govt_schemes: Mapped[list["GovtScheme"]] = relationship(back_populates="organization")
    generated_websites: Mapped[list["GeneratedWebsite"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class GeneratedWebsite(Base):
    """Last built static microsite for an organization (Part E)."""

    __tablename__ = "generated_websites"
    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_generated_websites_org"),
        UniqueConstraint("slug", name="uq_generated_websites_slug"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    template_type: Mapped[str] = mapped_column(String(32), nullable=False, default="shop")
    public_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    disk_path: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship(back_populates="generated_websites")


class Role(Base):
    """
    RBAC role scoped per organization (roadmap: id, org_id, name, level).

    DB column for the FK is `org_id`; Python attribute is `organization_id`.
    Same role name may repeat across organizations (e.g. each org has its own "owner").
    """

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_roles_org_id_name"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    organization_id: Mapped[int] = mapped_column(
        "org_id",
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)

    organization: Mapped["Organization"] = relationship(back_populates="roles")
    memberships: Mapped[list["UserOrganizationMembership"]] = relationship(back_populates="role")
    permissions: Mapped[list["Permission"]] = relationship(back_populates="role")


class Permission(Base):
    """Optional fine-grained grants; route guards may also use role name + level."""

    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    resource: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)

    role: Mapped["Role"] = relationship(back_populates="permissions")


class User(Base):
    """
    Identity account (email + password). Tenant and role live on ``UserOrganizationMembership`` rows
    so one user can belong to multiple organizations with different roles (Phase 2).
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    memberships: Mapped[list["UserOrganizationMembership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="user")
    personal_crypto: Mapped[Optional["UserPersonalCrypto"]] = relationship(back_populates="user")
    daily_planners: Mapped[list["DailyPlanner"]] = relationship(back_populates="user")
    daily_plan_agenda: Mapped[list["DailyPlan"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    research_vault_entries: Mapped[list["ResearchVault"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    research_corrections: Mapped[list["ResearchCorrection"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    health_logs: Mapped[list["HealthLog"]] = relationship(back_populates="user")
    personal_reminders: Mapped[list["PersonalReminder"]] = relationship(back_populates="user")
    habits: Mapped[list["Habit"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    personal_missions: Mapped[list["PersonalMission"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    personal_health_metrics: Mapped[list["PersonalHealthMetric"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    enc_notes: Mapped[list["EncNote"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    personal_engagement_row: Mapped[Optional["PersonalEngagement"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    personal_suggestion_feedback_rows: Mapped[list["PersonalSuggestionFeedback"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    project_staff_assignments: Mapped[list["ProjectStaffAssignment"]] = relationship(back_populates="user")
    department_leads: Mapped[list["Department"]] = relationship(
        back_populates="lead_user",
        foreign_keys="Department.lead_user_id",
    )
    staff_profile_rows: Mapped[list["StaffProfile"]] = relationship(back_populates="user")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    personal_expenses: Mapped[list["PersonalExpense"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    personal_loans: Mapped[list["PersonalLoan"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    vital_records: Mapped[list["VitalRecord"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    medicine_trackers: Mapped[list["MedicineTracker"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    doctor_visits: Mapped[list["DoctorVisit"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    research_projects: Mapped[list["ResearchProject"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    personal_budgets: Mapped[list["PersonalBudget"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    personal_meetings: Mapped[list["PersonalMeeting"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    user_integrations_rows: Mapped[list["UserIntegration"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    push_subscriptions: Mapped[list["PushSubscription"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    jarvis_memory_rows: Mapped[list["JarvisMemory"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    jarvis_proactive_alert_rows: Mapped[list["JarvisProactiveAlert"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    stock_watchlist_rows: Mapped[list["StockWatchlistEntry"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    equity_portfolio_positions: Mapped[list["EquityPortfolioPosition"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    equity_portfolio_transactions: Mapped[list["EquityPortfolioTransaction"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    research_document_rows: Mapped[list["ResearchDocument"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    govt_scheme_rows: Mapped[list["GovtScheme"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(Base):
    """
    Opaque refresh token (hash-only at rest). Phase 8: short-lived access JWT + rotatable refresh.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


class UserOrganizationMembership(Base):
    """
    Links a user to one organization with a role. Unique (user_id, organization_id).

    JWT ``active_org_id`` selects which membership row applies for the current request.
    """

    __tablename__ = "user_organization_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", name="uq_user_org_membership"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("roles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="memberships")
    organization: Mapped["Organization"] = relationship(back_populates="memberships")
    role: Mapped["Role"] = relationship(back_populates="memberships")


class UserPersonalCrypto(Base):
    """
    PBKDF2 salt + SHA-256 verifier of derived key (never store raw passphrase or Fernet key).
    Personal notes ciphertexts use Fernet keys derived from the same passphrase + salt.
    """

    __tablename__ = "user_personal_crypto"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    salt: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_verifier_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="personal_crypto")


class DailyPlanner(Base):
    __tablename__ = "daily_planner"
    __table_args__ = (UniqueConstraint("user_id", "for_date", name="uq_daily_planner_user_date"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    for_date: Mapped[date] = mapped_column(Date, nullable=False)
    blocks: Mapped[list[Any]] = mapped_column(
        "blocks",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=list,
    )
    private_notes_cipher: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    ai_flow_hint: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="daily_planners")


class DailyPlan(Base):
    """
    Executive **Daily Agenda**: markdown plan text per user per calendar day.

    Separate from ``daily_planner`` (JSON time blocks) — used by the dashboard Executive OS.
    """

    __tablename__ = "daily_plans"
    __table_args__ = (UniqueConstraint("user_id", "for_date", name="uq_daily_plans_user_for_date"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    for_date: Mapped[date] = mapped_column(Date, nullable=False)
    plan_text: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", server_default="draft")
    checklist_json: Mapped[list[Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=lambda: [],
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="daily_plan_agenda")


class DailyPlanSnapshot(Base):
    """Append-only history of executive daily plan saves (Markdown + checklist)."""

    __tablename__ = "daily_plan_snapshots"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    for_date: Mapped[date] = mapped_column(Date, nullable=False)
    plan_text: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    checklist_json: Mapped[list[Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=lambda: [],
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ExecutiveVaultDocument(Base):
    """User-uploaded PDFs/images (land docs, legal) for Executive OS vault."""

    __tablename__ = "executive_vault_documents"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ResearchVault(Base):
    """Persisted LLM research reports (Markdown), tenant- and user-scoped."""

    __tablename__ = "research_vault"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    report_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    business_category: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="auto_generated")
    resolved_symbol: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    price_at_save: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    quote_currency: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="research_vault_entries")


class ResearchCorrection(Base):
    """User feedback from Command Bar (etc.) injected into future research prompts."""

    __tablename__ = "research_corrections"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    feedback_text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="command_bar")
    related_research_vault_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("research_vault.id", ondelete="SET NULL"), nullable=True
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="research_corrections")


class HealthLog(Base):
    __tablename__ = "health_logs"
    __table_args__ = (UniqueConstraint("user_id", "logged_on", name="uq_health_logs_user_day"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    logged_on: Mapped[date] = mapped_column(Date, nullable=False)
    sleep_hours: Mapped[Optional[Decimal]] = mapped_column(Numeric(4, 2), nullable=True)
    water_glasses: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    stress_1_10: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    bp_systolic: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bp_diastolic: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reflection_cipher: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    reflection_encrypted: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="health_logs")


class PersonalReminder(Base):
    __tablename__ = "personal_reminders"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_cipher: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    body_encrypted: Mapped[bool] = mapped_column(default=False, nullable=False)
    done_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="personal_reminders")


class Habit(Base):
    """Personal habit tracker (Phase 3 Life OS)."""

    __tablename__ = "habits"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    goal_frequency: Mapped[str] = mapped_column(Text, nullable=False, default="daily")
    category: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    streak_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="habits")
    logs: Mapped[list["HabitLog"]] = relationship(back_populates="habit", cascade="all, delete-orphan")


class HabitLog(Base):
    __tablename__ = "habit_logs"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    habit_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("habits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed")

    habit: Mapped["Habit"] = relationship(back_populates="logs")


class PersonalMission(Base):
    """Personal goal / project (not tenant factory project)."""

    __tablename__ = "personal_missions"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deadline: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    priority: Mapped[str] = mapped_column(String(8), nullable=False, default="P2")
    progress_percent: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    source_ref: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="personal_missions")


class PersonalEngagement(Base):
    """Daily OS streak + lightweight JSON extras (action counts, last score) per user."""

    __tablename__ = "personal_engagement"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    last_active_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    streak_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    extra: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )

    user: Mapped["User"] = relationship(back_populates="personal_engagement_row")


class PersonalSuggestionFeedback(Base):
    """Thumbs-up/down on daily suggestions (also mirrored to ``learning_logs`` when org is present)."""

    __tablename__ = "personal_suggestion_feedback"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    suggestion_text: Mapped[str] = mapped_column(Text, nullable=False)
    helpful: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="personal_suggestion_feedback_rows")
    organization: Mapped[Optional["Organization"]] = relationship(
        back_populates="personal_suggestion_feedback"
    )


class PersonalHealthMetric(Base):
    """
    Time-series health entries (sleep / steps / mood, plus e.g. ``water`` for glasses from vault JSON).

    Physical table ``personal_health_metrics`` — distinct from legacy ``HealthLog`` on ``health_logs`` (daily row).
    """

    __tablename__ = "personal_health_metrics"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metric_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped["User"] = relationship(back_populates="personal_health_metrics")


class EncNote(Base):
    """Fernet-encrypted personal note (ciphertext only at rest)."""

    __tablename__ = "enc_notes"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    encrypted_content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="general")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="enc_notes")


class Approval(Base):
    """
    HITL queue row: every approval is tied to organization_id for multi-tenant isolation.

    Payload is JSONB (invoice drafts, future action blobs). status: pending | approved | rejected.
    """

    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=lambda: {})
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    risk_tier: Mapped[str] = mapped_column(String(16), nullable=False, default="high")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="approvals")


class LearningLog(Base):
    """
    Post-mortem row after HITL approval/rejection or after background execution.
    Feeds ``recursive_learning.lessons_prompt_block`` for council prompts (org-scoped).
    """

    __tablename__ = "learning_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    approval_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("approvals.id", ondelete="SET NULL"), nullable=True
    )
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    action_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    lesson_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=lambda: {})
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=lambda: {})
    user_feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolved_by_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship(back_populates="learning_logs")


class SystemAuditLog(Base):
    """
    Security-sensitive action trail (login, stock changes, posted invoices / financial execution).
    Populated by ``services.audit_log`` — not user-editable.
    """

    __tablename__ = "system_audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="success")
    resource_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    client_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    audit_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=lambda: {})
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization: Mapped[Optional["Organization"]] = relationship(back_populates="system_audit_logs")


class AuditLog(Base):
    """
    Control plane audit trail (enterprise UI → backend).

    Unlike ``SystemAuditLog`` (internal system security trail), this table stores *operator actions*
    with a stable schema for API queries and filters.
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        "org_id",
        BigInteger,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    entity: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    entity_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # AI|USER
    result: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # SUCCESS|FAIL
    audit_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=lambda: {})
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    organization: Mapped["Organization"] = relationship(back_populates="audit_logs")
    user: Mapped[Optional["User"]] = relationship(back_populates="audit_logs")


class ControlPlaneAlert(Base):
    __tablename__ = "control_plane_alerts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        "org_id",
        BigInteger,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True, default="warning")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved: Mapped[bool] = mapped_column(default=False, nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="control_plane_alerts")


class ControlPlaneJob(Base):
    __tablename__ = "control_plane_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        "org_id",
        BigInteger,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=lambda: {})
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="scheduled")
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="control_plane_jobs")


class SaasPlan(Base):
    __tablename__ = "saas_plans"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=lambda: {})
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SaasSubscription(Base):
    __tablename__ = "saas_subscriptions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        "org_id", BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("saas_plans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="active")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    external_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    organization: Mapped["Organization"] = relationship()
    plan: Mapped["SaasPlan"] = relationship()


class SaasUsageMetric(Base):
    __tablename__ = "saas_usage_metrics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        "org_id", BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    metric: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    value: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    organization: Mapped["Organization"] = relationship()
    user: Mapped[Optional["User"]] = relationship()


class AutonomySetting(Base):
    __tablename__ = "autonomy_settings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        "org_id",
        BigInteger,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    auto_mode_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=lambda: {})
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    organization: Mapped["Organization"] = relationship()


class AutonomyFeedback(Base):
    __tablename__ = "autonomy_feedback"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        "org_id", BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    decision_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    action_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    confidence: Mapped[Optional[float]] = mapped_column(sa.Float, nullable=True)  # type: ignore[name-defined]
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    organization: Mapped["Organization"] = relationship()
    user: Mapped[Optional["User"]] = relationship()


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    valuation: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    status_enum: Mapped[AssetStatusEnum] = mapped_column(
        Enum(AssetStatusEnum, name="asset_status_enum", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=AssetStatusEnum.active,
    )
    external_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="assets")
    production_logs: Mapped[list["ProductionLog"]] = relationship(back_populates="asset")
    linked_factory_projects: Mapped[list["ProjectStage"]] = relationship(back_populates="asset")


class Debt(Base):
    __tablename__ = "debts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    lender_name: Mapped[str] = mapped_column(Text, nullable=False)
    principal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    interest_rate: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(8, 4), nullable=True
    )  # annual % e.g. 26.5
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    category_enum: Mapped[DebtCategoryEnum] = mapped_column(
        Enum(DebtCategoryEnum, name="debt_category_enum", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=DebtCategoryEnum.other,
    )
    external_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    organization: Mapped[Optional["Organization"]] = relationship(back_populates="debts")


class Notification(Base):
    """Tenant-scoped alert row (low stock, overdue debt, etc.) — see workers.alert_system."""

    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("organization_id", "dedupe_key", name="uq_notifications_org_dedupe"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="warning")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    reference_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reference_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=lambda: {})
    dedupe_key: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="notifications")


class ComplianceCase(Base):
    """GST / Legal / Audit tracking; use ``external_ref`` e.g. ``statutory:gstr1:2026-03`` for calendar matching."""

    __tablename__ = "compliance_cases"
    __table_args__ = (
        UniqueConstraint("organization_id", "external_ref", name="uq_compliance_cases_org_external_ref"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(32), nullable=False, default="normal")
    deadline: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    external_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship(back_populates="compliance_cases")
    linked_comms: Mapped[list["CommsInbox"]] = relationship(back_populates="related_case")


class CommsInbox(Base):
    """Inbound Email / SMS / System messages classified by JARVIS Eye tier."""

    __tablename__ = "comms_inbox"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    sender: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body_summary: Mapped[str] = mapped_column(Text, nullable=False)
    intelligence_tier: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    related_case_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("compliance_cases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    message_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship(back_populates="comms_inbox")
    related_case: Mapped[Optional["ComplianceCase"]] = relationship(back_populates="linked_comms")


class Department(Base):
    """Tenant department (default **General** created by `core.db.provisioning`)."""

    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_departments_org_name"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    lead_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship(back_populates="departments")
    lead_user: Mapped[Optional["User"]] = relationship(
        back_populates="department_leads",
        foreign_keys=[lead_user_id],
    )
    staff_members: Mapped[list["StaffProfile"]] = relationship(back_populates="department")


class StaffProfile(Base):
    """HR-style row: one active profile per (user, organization)."""

    __tablename__ = "staff_profiles"
    __table_args__ = (UniqueConstraint("user_id", "organization_id", name="uq_staff_profiles_user_org"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    department_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    basic_salary: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    joining_date: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=func.current_date()
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="staff_profile_rows")
    organization: Mapped["Organization"] = relationship(back_populates="staff_profiles")
    department: Mapped[Optional["Department"]] = relationship(back_populates="staff_members")
    attendance_logs: Mapped[list["AttendanceLog"]] = relationship(
        back_populates="staff_profile", cascade="all, delete-orphan"
    )
    maintenance_logs_as_tech: Mapped[list["MaintenanceLog"]] = relationship(
        back_populates="technician_staff_profile",
    )
    work_orders_assigned: Mapped[list["WorkOrder"]] = relationship(
        back_populates="assigned_staff",
    )


class AttendanceLog(Base):
    """Daily attendance; ``staff_id`` references ``staff_profiles.id`` (staff profile row)."""

    __tablename__ = "attendance_logs"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    staff_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("staff_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    check_in: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    check_out: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="present")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    staff_profile: Mapped["StaffProfile"] = relationship(back_populates="attendance_logs")


class OperationalExpense(Base):
    """Manual / API-captured operational spend for net-profit rollup."""

    __tablename__ = "operational_expenses"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_inr: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship(back_populates="operational_expenses")


class AgroSubsidyCase(Base):
    """Government subsidy tracking per farmer (Agro Agency and similar tenants)."""

    __tablename__ = "agro_subsidy_cases"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    farmer_name: Mapped[str] = mapped_column(Text, nullable=False)
    village: Mapped[str] = mapped_column(Text, nullable=False, default="")
    survey_number: Mapped[str] = mapped_column(Text, nullable=False, default="")
    farmer_phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    land_acres: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4), nullable=True)
    scheme_name: Mapped[str] = mapped_column(Text, nullable=False)
    application_status: Mapped[str] = mapped_column(String(64), nullable=False, default="draft")
    subsidy_applied_inr: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    subsidy_approved_inr: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    subsidy_pending_inr: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    subsidy_received_inr: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    commission_earned_inr: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    follow_up_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship(back_populates="agro_subsidy_cases")


class BusinessTask(Base):
    """Operational tasks, checklists, and reminders per organization."""

    __tablename__ = "business_tasks"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    owner_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    task_type: Mapped[str] = mapped_column(String(64), nullable=False, default="general")
    checklist_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship(back_populates="business_tasks")


class Inventory(Base):
    __tablename__ = "inventory"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    organization_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    sku_name: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    location: Mapped[str] = mapped_column(Text, nullable=False, default="")
    unit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    unit_cost_pre_tax: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    total_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    # Total GST % for the SKU (e.g. 18). Bill uses CGST+SGST (intra-state) or IGST (inter-state).
    gst_rate_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    # HSN (goods) / SAC (services) for statutory tax invoices.
    hsn_code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    external_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Invoice(Base):
    """Posted invoice lines for revenue aggregation (see services.financial_analytics)."""

    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invoice_no: Mapped[str] = mapped_column(Text, nullable=False, default="")
    invoice_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    grand_total_inr: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    production_log_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("production_logs.id", ondelete="SET NULL"), nullable=True
    )
    external_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Phase 2 — structured billing lifecycle (defaults keep legacy rows valid)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="posted", server_default="posted")
    payment_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unpaid", server_default="unpaid")
    eway_bill_no: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    vehicle_no: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transport_mode: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    consignee_place: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="invoices")
    line_items: Mapped[list["InvoiceItem"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )
    payments: Mapped[list["Payment"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")


class Bill(Base):
    """
    Point-of-sale style bill: line items (JSON), total, timestamp.
    Complements ``invoices`` (PDF/revenue pipeline); used for retail sell_stock flow.
    """

    __tablename__ = "bills"

    # Integer variant on SQLite so autoincrement works in CI / local tests; PostgreSQL uses BIGINT.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Retail lines: sku_name, quantity, unit_price_pre_tax, taxable_value, gst_*, line_total_with_tax
    items: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship(back_populates="bills")


class ProductionLog(Base):
    __tablename__ = "production_logs"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    production_unit: Mapped[str] = mapped_column(String(64), nullable=False, default="general")
    cement_in: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    sand_in: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    blocks_out: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    raw_material_in: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    yield_out: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    labor_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    external_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    machine_hours: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    quality_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    asset: Mapped["Asset"] = relationship(back_populates="production_logs")


class FactoryBillingHold(Base):
    """When set, high-risk billing / invoice execution paths should refuse (Stage-2 machine down)."""

    __tablename__ = "factory_billing_hold"

    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    billing_paused: Mapped[bool] = mapped_column(default=False, nullable=False)
    pause_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship(back_populates="factory_billing_hold_row")


class ProjectStage(Base):
    """
    Factory lifecycle: **2** Income-generating (live), **3** Repair/revive, **4** New setup (expansion).
    """

    __tablename__ = "project_stages"

    STAGE_INCOME = 2
    STAGE_REPAIR = 3
    STAGE_EXPANSION = 4

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_name: Mapped[str] = mapped_column(Text, nullable=False)
    current_stage: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    asset_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("assets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    revival_cost_inr: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    machine_failed: Mapped[bool] = mapped_column(default=False, nullable=False)
    extra: Mapped[dict[str, Any]] = mapped_column(
        "extra",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship(back_populates="factory_projects")
    asset: Mapped[Optional["Asset"]] = relationship(back_populates="linked_factory_projects")
    staff_assignments: Mapped[list["ProjectStaffAssignment"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    equipment_items: Mapped[list["Equipment"]] = relationship(back_populates="project_stage")
    work_orders: Mapped[list["WorkOrder"]] = relationship(
        back_populates="project_stage", cascade="all, delete-orphan"
    )


class ProjectStaffAssignment(Base):
    __tablename__ = "project_staff_assignments"
    __table_args__ = (UniqueConstraint("project_stage_id", "user_id", name="uq_project_staff_user"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    project_stage_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("project_stages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped["ProjectStage"] = relationship(back_populates="staff_assignments")
    user: Mapped["User"] = relationship(back_populates="project_staff_assignments")


class Equipment(Base):
    """Factory floor equipment registry (Phase 6). Status: Running | Down | Maintenance."""

    __tablename__ = "equipment"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_stage_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("project_stages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    purchase_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    last_service_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    next_service_due: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="Running", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship(back_populates="equipment")
    project_stage: Mapped[Optional["ProjectStage"]] = relationship(back_populates="equipment_items")
    maintenance_logs: Mapped[list["MaintenanceLog"]] = relationship(
        back_populates="equipment", cascade="all, delete-orphan"
    )
    work_orders: Mapped[list["WorkOrder"]] = relationship(back_populates="equipment")


class MaintenanceLog(Base):
    """Repair history; ``cost`` rolls into ``economics_service`` net profit for the month when ``fixed_at`` is set."""

    __tablename__ = "maintenance_logs"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    equipment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False, index=True
    )
    issue_description: Mapped[str] = mapped_column(Text, nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    fixed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    technician_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    technician_staff_profile_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("staff_profiles.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    equipment: Mapped["Equipment"] = relationship(back_populates="maintenance_logs")
    technician_staff_profile: Mapped[Optional["StaffProfile"]] = relationship(
        back_populates="maintenance_logs_as_tech"
    )


class WorkOrder(Base):
    """Ties a factory project stage to equipment and optional staff assignment."""

    __tablename__ = "work_orders"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    project_stage_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("project_stages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    equipment_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("equipment.id", ondelete="SET NULL"), nullable=True, index=True
    )
    assigned_staff_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("staff_profiles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    priority: Mapped[str] = mapped_column(String(32), nullable=False, default="normal")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open", index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    project_stage: Mapped["ProjectStage"] = relationship(back_populates="work_orders")
    equipment: Mapped[Optional["Equipment"]] = relationship(back_populates="work_orders")
    assigned_staff: Mapped[Optional["StaffProfile"]] = relationship(back_populates="work_orders_assigned")


class IdempotencyKey(Base):
    """
    Completed (or in-flight) automation keys — prevents duplicate invoice / brain-intent execution
    across API replicas and worker processes. See ``workers.idempotency``.
    """

    __tablename__ = "idempotency_keys"

    idempotency_key: Mapped[str] = mapped_column(String(512), primary_key=True)
    action_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    meta: Mapped[dict[str, Any]] = mapped_column(
        "meta",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AiHitlFeedback(Base):
    """
    Human-in-the-loop signals to refine policy strictness per business rule (typically ``tool_id``).
    """

    __tablename__ = "ai_hitl_feedback"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    rule_key: Mapped[str] = mapped_column(String(128), nullable=False)
    sentiment: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AiRuleWeight(Base):
    """
    Aggregated HITL weight per org + rule_key. Baseline 1.0; higher ⇒ stricter post-processing in policy.
    """

    __tablename__ = "ai_rule_weights"
    __table_args__ = (PrimaryKeyConstraint("organization_id", "rule_key"),)

    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    rule_key: Mapped[str] = mapped_column(String(128), nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False, server_default="1.000", default=Decimal("1"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class LedgerTransaction(Base):
    """
    ERP ledger row (revenue / expense / adjustment). Complements ``invoices`` / ``bills`` with a queryable journal.

    Maps the architecture doc ``transactions`` table to ``ledger_transactions`` to avoid SQL keyword noise.
    """

    __tablename__ = "ledger_transactions"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    entry_type: Mapped[str] = mapped_column(String(32), nullable=False, default="adjustment")
    amount_inr: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="general")
    reference: Mapped[str] = mapped_column(Text, nullable=False, default="")
    extra: Mapped[dict[str, Any]] = mapped_column(
        "extra",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship(back_populates="ledger_transactions")
    user: Mapped[Optional["User"]] = relationship()


class BackgroundJob(Base):
    """
    DB queue row for cross-process work. API inserts ``pending``; worker claims with ``FOR UPDATE SKIP LOCKED``.
    """

    __tablename__ = "background_jobs"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    organization_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(512), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        "payload",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


# --- Phase 2: enterprise inventory (inventory_items + movements + procurement) ---


class InventoryItem(Base):
    """
    Canonical SKU row per org + location (mirrors legacy ``inventory`` for API v2).
    Application layer may sync quantities to ``Inventory`` for legacy sell flows.
    """

    __tablename__ = "inventory_items"
    __table_args__ = (
        UniqueConstraint("organization_id", "sku_name", "location", name="uq_inventory_items_org_sku_loc"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sku_name: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    location: Mapped[str] = mapped_column(Text, nullable=False, default="")
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    unit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    unit_cost_pre_tax: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    total_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    gst_rate_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    hsn_code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    external_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reorder_point: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship(back_populates="inventory_items_v2")
    stock_movements: Mapped[list["StockMovement"]] = relationship(
        back_populates="inventory_item", cascade="all, delete-orphan"
    )


class StockMovement(Base):
    """Auditable quantity delta (in/out) for an ``inventory_items`` row."""

    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    inventory_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    movement_type: Mapped[str] = mapped_column(String(32), nullable=False, default="ADJUST")
    reference_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reference_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lot_batch: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    inventory_item: Mapped["InventoryItem"] = relationship(back_populates="stock_movements")


class Supplier(Base):
    """Vendor master data (GST-ready)."""

    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    gstin: Mapped[Optional[str]] = mapped_column(String(15), nullable=True)
    contact_email: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship(back_populates="suppliers")
    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(back_populates="supplier")
    payments: Mapped[list["SupplierPayment"]] = relationship(back_populates="supplier")


class PurchaseOrder(Base):
    """Procurement header."""

    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    supplier_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    supplier_invoice_no: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    supplier_invoice_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    total_inr: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship(back_populates="purchase_orders")
    supplier: Mapped["Supplier"] = relationship(back_populates="purchase_orders")
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="purchase_order", cascade="all, delete-orphan"
    )


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    purchase_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sku_name: Mapped[str] = mapped_column(Text, nullable=False)
    quantity_ordered: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    quantity_received: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    unit_cost_pre_tax: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    line_total_inr: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="lines")


class SupplierPayment(Base):
    """Payment to supplier (against PO or ad-hoc)."""

    __tablename__ = "supplier_payments"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    supplier_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purchase_order_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("purchase_orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    amount_inr: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False, default="bank")
    reference: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship(back_populates="supplier_payments")
    supplier: Mapped["Supplier"] = relationship(back_populates="payments")


class OrganizationLiquidity(Base):
    """Manual cash / bank position per tenant (shop counter + bank balance)."""

    __tablename__ = "organization_liquidity"

    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    cash_inr: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    bank_inr: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship(back_populates="liquidity_row")


# --- Phase 2: structured billing (line items + payments + GST snapshots) ---


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    invoice_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("1"))
    unit_price_pre_tax: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    gst_rate_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0"))
    line_total_inr: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    hsn_code: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    invoice: Mapped["Invoice"] = relationship(back_populates="line_items")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invoice_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount_inr: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False, default="bank")
    reference: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    invoice: Mapped["Invoice"] = relationship(back_populates="payments")


class GstRecord(Base):
    """Monthly GST summary snapshot for reporting (JSON payload)."""

    __tablename__ = "gst_records"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    data: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship(back_populates="gst_records")


class RawMaterial(Base):
    """Stock of raw inputs (separate from finished SKU ``inventory_items``)."""

    __tablename__ = "raw_materials"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="kg")
    quantity_on_hand: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    reorder_point: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship(back_populates="raw_materials")


class AiDecision(Base):
    """
    Phase 3 — AI decision engine: structured proposals and execution outcomes (tenant-scoped).
    """

    __tablename__ = "ai_decisions"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    requires_approval: Mapped[bool] = mapped_column(default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    execution_result: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    resolved_by_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="ai_decisions")


class UsageLog(Base):
    """Product analytics: login, feature use, AI outcomes (tenant-scoped, optional user)."""

    __tablename__ = "usage_logs"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    organization_id: Mapped[int] = mapped_column(
        "org_id",
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    event_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(
        "metadata",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship(back_populates="usage_logs")


class PersonalExpense(Base):
    """User-scoped personal finance line (not tenant operational expense)."""

    __tablename__ = "personal_expenses"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    subcategory: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    spent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    notes_cipher: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    notes_encrypted: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="personal_expenses")


class PersonalLoan(Base):
    """Personal liabilities: EMI, chit, jewel loan, etc."""

    __tablename__ = "personal_loans"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    loan_kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    lender: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    principal_outstanding: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 2), nullable=True)
    emi_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    next_due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    interest_rate_apr: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 3), nullable=True)
    is_closed: Mapped[bool] = mapped_column(default=False, nullable=False)
    notes_cipher: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    notes_encrypted: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="personal_loans")


class VitalRecord(Base):
    """Clinical-style vitals (weight, BP, glucose) — optional encrypted notes."""

    __tablename__ = "vital_records"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    weight_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    bp_systolic: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bp_diastolic: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    blood_glucose_mg_dl: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    sleep_hours: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    stress_1_10: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    water_glasses: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notes_cipher: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    notes_encrypted: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="vital_records")


class MedicineTracker(Base):
    """Medicine / supplement schedule (JSON schedule; optional encrypted notes)."""

    __tablename__ = "medicine_trackers"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    dosage_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    schedule_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    started_on: Mapped[date] = mapped_column(Date, nullable=False)
    ended_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)
    notes_cipher: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    notes_encrypted: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="medicine_trackers")


class DoctorVisit(Base):
    """Doctor visit log; diagnosis may be ciphertext."""

    __tablename__ = "doctor_visits"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    visited_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    doctor_name: Mapped[str] = mapped_column(Text, nullable=False)
    specialty: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    location: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    diagnosis_cipher: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    prescription_cipher: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    diagnosis_encrypted: Mapped[bool] = mapped_column(default=False, nullable=False)
    follow_up_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="doctor_visits")


class ResearchProject(Base):
    """Personal research / DPR-style project (Phase 1 shell; AI in Phase 2)."""

    __tablename__ = "research_projects"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    links_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="research_projects")


class PersonalBudget(Base):
    """Budget envelope per category for a date window."""

    __tablename__ = "personal_budgets"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    period_end: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    subcategory: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    budget_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    overspend_alert_pct: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=15)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="personal_budgets")


class UserIntegration(Base):
    """OAuth-connected third-party accounts (e.g. Google Calendar) per user."""

    __tablename__ = "user_integrations"
    __table_args__ = (UniqueConstraint("user_id", "integration_type", name="uq_user_integrations_user_type"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    integration_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    access_token_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    refresh_token_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    scope: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="user_integrations_rows")


class PushSubscription(Base):
    """Browser Web Push subscription (VAPID); one row per endpoint (device)."""

    __tablename__ = "push_subscriptions"
    __table_args__ = (UniqueConstraint("endpoint", name="uq_push_subscriptions_endpoint"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    keys_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="push_subscriptions")


class PersonalMeeting(Base):
    """Personal / business meetings and appointments (Personal Command Center)."""

    __tablename__ = "personal_meetings"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[int] = mapped_column(
        "organization_id",
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    meeting_type: Mapped[str] = mapped_column(String(32), nullable=False, default="other", index=True)
    location_type: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    location_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    location_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    location_maps_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled", index=True)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    agenda: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outcome: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    arranged_by: Mapped[str] = mapped_column(String(16), nullable=False, default="self")
    organizer_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    organizer_phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    organizer_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    attendees_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=list,
    )
    reminder_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    is_recurring: Mapped[bool] = mapped_column(default=False, nullable=False)
    recurrence_rule: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    google_event_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="personal_meetings")
    organization: Mapped["Organization"] = relationship(back_populates="personal_meetings")


class JarvisMemory(Base):
    """User-specific Jarvis preferences / learned facts (Phase 2 agent)."""

    __tablename__ = "jarvis_memory"
    __table_args__ = (UniqueConstraint("user_id", "memory_key", name="uq_jarvis_memory_user_key"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    memory_key: Mapped[str] = mapped_column(String(512), nullable=False)
    memory_value: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0.5"))
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="jarvis_memory_rows")


class JarvisProactiveAlert(Base):
    """Morning intelligence and follow-ups surfaced in Today brief + Jarvis."""

    __tablename__ = "jarvis_proactive_alerts"
    __table_args__ = (UniqueConstraint("user_id", "dedupe_key", name="uq_jarvis_proactive_user_dedupe"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    action_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    dedupe_key: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="jarvis_proactive_alert_rows")
    organization: Mapped[Optional["Organization"]] = relationship()


class StockWatchlistEntry(Base):
    """User NSE/BSE watchlist symbols for Jarvis market tools."""

    __tablename__ = "stock_watchlist_entries"
    __table_args__ = (UniqueConstraint("user_id", "symbol", name="uq_stock_watchlist_user_symbol"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange_suffix: Mapped[str] = mapped_column(String(8), nullable=False, default="NS")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="stock_watchlist_rows")


class EquityPortfolioPosition(Base):
    """User equity paper portfolio (symbol lot + average cost)."""

    __tablename__ = "equity_portfolio_positions"
    __table_args__ = (
        UniqueConstraint("user_id", "symbol", "exchange_suffix", name="uq_equity_position_user_sym_ex"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange_suffix: Mapped[str] = mapped_column(String(8), nullable=False, default="NS")
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))
    avg_buy_price_inr: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="equity_portfolio_positions")


class EquityPortfolioTransaction(Base):
    """Buy/sell ledger for equity paper portfolio."""

    __tablename__ = "equity_portfolio_transactions"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange_suffix: Mapped[str] = mapped_column(String(8), nullable=False, default="NS")
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    price_inr: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    fees_inr: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    realized_pnl_inr: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="equity_portfolio_transactions")


class ResearchDocument(Base):
    """Structured research outputs (market, DPR, competitors) keyed by user + optional org."""

    __tablename__ = "research_documents"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="research_document_rows")
    organization: Mapped[Optional["Organization"]] = relationship(back_populates="research_documents")


class GovtScheme(Base):
    """Government scheme rows discovered via research engine (Tavily + LLM extraction)."""

    __tablename__ = "govt_schemes"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    organization_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sector: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    state: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    scheme_name: Mapped[str] = mapped_column(Text, nullable=False)
    eligibility: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    subsidy_amount: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    application_process: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deadline: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[Optional["User"]] = relationship(back_populates="govt_scheme_rows")
    organization: Mapped[Optional["Organization"]] = relationship(back_populates="govt_schemes")


# Back-compat alias (deprecated)
Org = Organization
