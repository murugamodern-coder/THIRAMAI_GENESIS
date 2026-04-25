"""SQLAlchemy ORM for THIRAMAI V2.1 — see db/db_schema.sql."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    LargeBinary,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
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
    domain_dominion_profiles: Mapped[list["DomainDominionProfile"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    domain_revenue_ledger: Mapped[list["DomainRevenueLedger"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    decision_intelligence_sessions: Mapped[list["DecisionIntelligenceSession"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
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
    research_projects: Mapped[list["ResearchProject"]] = relationship(
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
    role_permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )
    users: Mapped[list["User"]] = relationship(
        back_populates="role",
        foreign_keys="User.role_id",
    )


class Permission(Base):
    """Optional fine-grained grants; route guards may also use role name + level."""

    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    resource: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)

    role: Mapped["Role"] = relationship(back_populates="permissions")
    role_permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="permission", cascade="all, delete-orphan"
    )


class RolePermission(Base):
    """Extensible many-to-many grants from roles to permission catalog entries."""

    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permissions_role_permission"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    role_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    permission_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("permissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    role: Mapped["Role"] = relationship(back_populates="role_permissions")
    permission: Mapped["Permission"] = relationship(back_populates="role_permissions")


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
    name: Mapped[str] = mapped_column(String(160), nullable=False, default="", server_default="")
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role_id: Mapped[Optional[int]] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("roles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    product_profile: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True, default=None
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
    action_execution_runs: Mapped[list["ActionExecutionRun"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    execution_memory_entries: Mapped[list["ExecutionMemoryEntry"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    continuity_goals: Mapped[list["ContinuityGoal"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    continuity_user_settings: Mapped[list["ContinuityUserSettings"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    domain_dominion_profiles: Mapped[list["DomainDominionProfile"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    domain_revenue_ledger: Mapped[list["DomainRevenueLedger"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    decision_intelligence_sessions: Mapped[list["DecisionIntelligenceSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    personal_budgets: Mapped[list["PersonalBudget"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    personal_meetings: Mapped[list["PersonalMeeting"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    financial_audit_logs: Mapped[list["FinancialAuditLog"]] = relationship(back_populates="user")
    user_integrations_rows: Mapped[list["UserIntegration"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    push_subscriptions: Mapped[list["PushSubscription"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    jarvis_memory_rows: Mapped[list["JarvisMemory"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    jarvis_episode_rows: Mapped[list["JarvisEpisode"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    jarvis_fact_rows: Mapped[list["JarvisFact"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    jarvis_session_rows: Mapped[list["JarvisSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    jarvis_proactive_alert_rows: Mapped[list["JarvisProactiveAlert"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    jarvis_proactive_feedback_rows: Mapped[list["JarvisProactiveFeedback"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    jarvis_goal_rows: Mapped[list["JarvisGoal"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    jarvis_daily_agent_plan_rows: Mapped[list["JarvisDailyAgentPlan"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    jarvis_agent_action_log_rows: Mapped[list["JarvisAgentActionLog"]] = relationship(
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
    stock_price_alert_rows: Mapped[list["StockPriceAlert"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    research_document_rows: Mapped[list["ResearchDocument"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    govt_scheme_rows: Mapped[list["GovtScheme"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    runtime_configs: Mapped[list["UserRuntimeConfig"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    missions: Mapped[list["Mission"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    automation_rules: Mapped[list["AutomationRule"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    automation_logs: Mapped[list["AutomationLog"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    integrations_rows: Mapped[list["Integration"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    integration_message_logs: Mapped[list["IntegrationMessageLog"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    opportunities_rows: Mapped[list["Opportunity"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    strategy_profiles: Mapped[list["StrategyProfile"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    strategy_experiments: Mapped[list["StrategyExperiment"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    real_world_executions: Mapped[list["RealWorldExecution"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    negotiation_deals: Mapped[list["NegotiationDeal"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    guardrails: Mapped[list["Guardrail"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    execution_audit_logs: Mapped[list["ExecutionAuditLog"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    money_loop_configs: Mapped[list["MoneyLoopConfig"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    role: Mapped[Optional["Role"]] = relationship(
        back_populates="users",
        foreign_keys=[role_id],
    )


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_created", "user_id", "created_at"),)

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
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="New conversation")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="conversations")
    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class ConversationMessage(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        sa.CheckConstraint("role in ('user','assistant')", name="ck_messages_role"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    conversation_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class Mission(Base):
    __tablename__ = "missions"
    __table_args__ = (
        Index("ix_missions_user_created", "user_id", "created_at"),
        sa.CheckConstraint("status in ('planned','running','completed')", name="ck_missions_status"),
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
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="planned")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="missions")
    steps: Mapped[list["MissionStep"]] = relationship(
        back_populates="mission", cascade="all, delete-orphan"
    )


class MissionStep(Base):
    __tablename__ = "mission_steps"
    __table_args__ = (
        Index("ix_mission_steps_mission_order", "mission_id", "step_order"),
        sa.CheckConstraint("status in ('pending','running','done','failed')", name="ck_mission_steps_status"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    mission_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    result_json: Mapped[dict[str, Any]] = mapped_column(
        "result",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    mission: Mapped["Mission"] = relationship(back_populates="steps")


class ContinuityGoal(Base):
    """Long-term autonomous goals (persist across sessions; driven by continuity tick)."""

    __tablename__ = "continuity_goals"
    __table_args__ = (
        Index("ix_continuity_goals_user_status", "user_id", "status"),
        sa.CheckConstraint(
            "status in ('active','paused','completed','cancelled','interrupted','waiting_action')",
            name="ck_continuity_goals_status",
        ),
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
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    deadline: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    progress_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    steps_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_steps_est: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    remaining_actions_json: Mapped[dict[str, Any]] = mapped_column(
        "remaining_actions_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    completed_steps_json: Mapped[dict[str, Any]] = mapped_column(
        "completed_steps_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    meta_json: Mapped[dict[str, Any]] = mapped_column(
        "meta_json",
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

    user: Mapped["User"] = relationship(back_populates="continuity_goals")
    action_runs: Mapped[list["ActionExecutionRun"]] = relationship(back_populates="continuity_goal")


class ContinuityUserSettings(Base):
    """Per user+org autonomy level and budgets for the continuity engine."""

    __tablename__ = "continuity_user_settings"
    __table_args__ = (UniqueConstraint("user_id", "organization_id", name="uq_continuity_settings_user_org"),)

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
    autonomy_level: Mapped[str] = mapped_column(String(32), nullable=False, default="assist")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    time_budget_minutes_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    capital_budget: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    effort_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    allow_auto_batch_medium: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_tick_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    runs_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    meta_json: Mapped[dict[str, Any]] = mapped_column(
        "meta_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="continuity_user_settings")


class DomainDominionProfile(Base):
    """Per user+org: active vertical focus, aggregated knowledge, and weekly review cursor."""

    __tablename__ = "domain_dominion_profiles"
    __table_args__ = (UniqueConstraint("user_id", "organization_id", name="uq_domain_dominion_user_org"),)

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
    active_domain: Mapped[str] = mapped_column(String(64), nullable=False, default="business")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    knowledge_json: Mapped[dict[str, Any]] = mapped_column(
        "knowledge_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    meta_json: Mapped[dict[str, Any]] = mapped_column(
        "meta_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    last_weekly_review_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="domain_dominion_profiles")
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="domain_dominion_profiles",  # type: ignore[assignment]
    )
    revenue_events: Mapped[list["DomainRevenueLedger"]] = relationship(back_populates="domain_profile")


class DomainRevenueLedger(Base):
    """Income, cost, and adjustment lines for domain P&L tracking (supplements LearningLog revenue)."""

    __tablename__ = "domain_revenue_ledger"
    __table_args__ = (Index("ix_domain_revenue_user_created", "user_id", "created_at"),)

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
    profile_id: Mapped[Optional[int]] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("domain_dominion_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    domain: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    ref_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    ref_id: Mapped[Optional[int]] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=True, index=True
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta_json: Mapped[dict[str, Any]] = mapped_column(
        "meta_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    user: Mapped["User"] = relationship(back_populates="domain_revenue_ledger")
    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="domain_revenue_ledger"  # type: ignore[assignment]
    )
    domain_profile: Mapped[Optional[DomainDominionProfile]] = relationship(
        "DomainDominionProfile", back_populates="revenue_events"
    )


class DecisionIntelligenceSession(Base):
    """
    Multi-option decision support: aggressive / balanced / safe with stored selection and outcome for learning.
    """

    __tablename__ = "decision_intelligence_sessions"
    __table_args__ = (
        Index("ix_decision_intel_user_created", "user_id", "created_at"),
        sa.CheckConstraint(
            "status in ('draft','selected','closed')",
            name="ck_decision_intel_status",
        ),
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
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    decision_brief: Mapped[str] = mapped_column(Text, nullable=False, default="")
    context_json: Mapped[dict[str, Any]] = mapped_column(
        "context_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    options_json: Mapped[dict[str, Any]] = mapped_column(
        "options_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    recommendation_json: Mapped[dict[str, Any]] = mapped_column(
        "recommendation_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    selected_option: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    result_json: Mapped[dict[str, Any]] = mapped_column(
        "result_json",
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

    user: Mapped["User"] = relationship(back_populates="decision_intelligence_sessions")
    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="decision_intelligence_sessions"  # type: ignore[assignment]
    )


class ActionExecutionRun(Base):
    """Persisted multi-step real-action plan (search → analyze → decide → act) with confirmation gates."""

    __tablename__ = "action_execution_runs"
    __table_args__ = (
        Index("ix_action_execution_runs_user_created", "user_id", "created_at"),
        Index("ix_action_execution_runs_user_status", "user_id", "status"),
        sa.CheckConstraint(
            "status in ('planned','awaiting_confirmation','running','completed','failed','cancelled')",
            name="ck_action_execution_runs_status",
        ),
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
    source_command: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="planned")
    continuity_goal_id: Mapped[Optional[int]] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("continuity_goals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    meta_json: Mapped[dict[str, Any]] = mapped_column(
        "meta_json",
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

    user: Mapped["User"] = relationship(back_populates="action_execution_runs")
    continuity_goal: Mapped[Optional["ContinuityGoal"]] = relationship(back_populates="action_runs")
    steps: Mapped[list["ActionExecutionStep"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="ActionExecutionStep.step_order"
    )


class ActionExecutionStep(Base):
    __tablename__ = "action_execution_steps"
    __table_args__ = (
        Index("ix_action_execution_steps_run_order", "run_id", "step_order"),
        sa.CheckConstraint(
            "phase in ('search','analyze','decide','act')",
            name="ck_action_execution_steps_phase",
        ),
        sa.CheckConstraint(
            "risk_level in ('low','medium','high')",
            name="ck_action_execution_steps_risk_level",
        ),
        sa.CheckConstraint(
            "status in ('pending','awaiting_confirmation','blocked','running','done','failed','skipped')",
            name="ck_action_execution_steps_status",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    run_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("action_execution_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    step_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        "payload_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    result_json: Mapped[dict[str, Any]] = mapped_column(
        "result_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    explicit_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    run: Mapped["ActionExecutionRun"] = relationship(back_populates="steps")


class ExecutionMemoryEntry(Base):
    """Outcome memory for action layer (what worked / failed) keyed by fingerprint."""

    __tablename__ = "execution_memory_entries"
    __table_args__ = (Index("ix_execution_memory_user_fp", "user_id", "fingerprint"),)

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
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    step_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    summary: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    detail_json: Mapped[dict[str, Any]] = mapped_column(
        "detail_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="execution_memory_entries")


class AutomationRule(Base):
    __tablename__ = "automation_rules"
    __table_args__ = (
        Index("ix_automation_rules_user_enabled", "user_id", "enabled"),
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
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(64), nullable=False)
    condition_json: Mapped[dict[str, Any]] = mapped_column(
        "condition_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    action_config_json: Mapped[dict[str, Any]] = mapped_column(
        "action_config_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="automation_rules")


class AutomationLog(Base):
    __tablename__ = "automation_logs"
    __table_args__ = (Index("ix_automation_logs_user_created", "user_id", "created_at"),)

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
    rule_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("automation_rules.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    trigger_type: Mapped[str] = mapped_column(String(64), nullable=False)
    event_json: Mapped[dict[str, Any]] = mapped_column(
        "event_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    action_taken: Mapped[str] = mapped_column(String(64), nullable=False)
    action_result_json: Mapped[dict[str, Any]] = mapped_column(
        "action_result_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="automation_logs")


class Integration(Base):
    __tablename__ = "integrations"
    __table_args__ = (Index("ix_integrations_user_type", "user_id", "type"),)

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
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(
        "config_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="integrations_rows")


class IntegrationMessageLog(Base):
    __tablename__ = "integration_message_logs"
    __table_args__ = (
        Index("ix_integration_message_logs_user_created", "user_id", "created_at"),
        Index("ix_integration_message_logs_integration", "integration_id", "created_at"),
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
    integration_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("integrations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    recipient: Mapped[str] = mapped_column(String(300), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(300), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="success")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="integration_message_logs")


class Opportunity(Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        Index("ix_opportunities_user_status_created", "user_id", "status", "created_at"),
        sa.CheckConstraint("status in ('new','approved','executed','rejected')", name="ck_opportunities_status"),
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
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expected_profit: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="new")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="opportunities_rows")
    profit_logs: Mapped[list["OpportunityProfitLog"]] = relationship(
        back_populates="opportunity", cascade="all, delete-orphan"
    )


class OpportunityProfitLog(Base):
    __tablename__ = "opportunity_profit_logs"
    __table_args__ = (Index("ix_opp_profit_logs_opp_created", "opportunity_id", "created_at"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    opportunity_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("opportunities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    profit_loss_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    opportunity: Mapped["Opportunity"] = relationship(back_populates="profit_logs")


class StrategyProfile(Base):
    __tablename__ = "strategy_profiles"
    __table_args__ = (
        Index("ix_strategy_profiles_user_domain", "user_id", "domain"),
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
    domain: Mapped[str] = mapped_column(String(32), nullable=False)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(
        "parameters_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    performance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="strategy_profiles")


class StrategyExperiment(Base):
    """Persistent experiment row per strategy: hypothesis, execution, outcome (feeds learning + strategy profiles)."""

    __tablename__ = "strategy_experiments"
    __table_args__ = (
        Index("ix_strategy_experiments_user_group_created", "user_id", "experiment_group", "created_at"),
        Index("ix_strategy_experiments_user_status", "user_id", "status"),
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
    strategy_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    experiment_group: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    strategy_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        "strategy_snapshot_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False, default="")
    execution_json: Mapped[dict[str, Any]] = mapped_column(
        "execution_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    result_json: Mapped[dict[str, Any]] = mapped_column(
        "result_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    success: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    learning_log_id: Mapped[Optional[int]] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("learning_logs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["User"] = relationship(back_populates="strategy_experiments")
    learning_log: Mapped[Optional["LearningLog"]] = relationship(foreign_keys=[learning_log_id])


class RealWorldExecution(Base):
    """Long-running real-world action: API success is not enough — track until verified outcome."""

    __tablename__ = "real_world_executions"
    __table_args__ = (
        Index("ix_rwe_user_state_created", "user_id", "state", "created_at"),
        sa.CheckConstraint(
            "state in ('initiated','in_progress','completed','failed')",
            name="ck_rwe_state",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    public_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
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
    action_type: Mapped[str] = mapped_column(String(64), nullable=False, default="general")
    label: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="initiated")
    expected_outcome_json: Mapped[dict[str, Any]] = mapped_column(
        "expected_outcome_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    actual_outcome_json: Mapped[dict[str, Any]] = mapped_column(
        "actual_outcome_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    api_succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    outcome_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    outcome_assessment: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    verification_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    meta_json: Mapped[dict[str, Any]] = mapped_column(
        "meta_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="real_world_executions")


class NegotiationDeal(Base):
    """Per-deal negotiation memory and status (message loop)."""

    __tablename__ = "negotiation_deals"
    __table_args__ = (
        Index("ix_negdeals_user_status", "user_id", "status"),
        sa.CheckConstraint(
            "status in ('open','negotiating','closed','lost')",
            name="ck_negdeal_status",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    public_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
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
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    context_json: Mapped[dict[str, Any]] = mapped_column(
        "context_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    messages_json: Mapped[Any] = mapped_column(
        "messages_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=list,
    )
    last_analysis_json: Mapped[dict[str, Any]] = mapped_column(
        "last_analysis_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="negotiation_deals")


class Guardrail(Base):
    __tablename__ = "guardrails"
    __table_args__ = (
        Index("ix_guardrails_user_domain_enabled", "user_id", "domain", "enabled"),
        UniqueConstraint("user_id", "rule_name", "domain", name="uq_guardrails_user_rule_domain"),
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
    rule_name: Mapped[str] = mapped_column(String(120), nullable=False)
    domain: Mapped[str] = mapped_column(String(32), nullable=False)
    condition_json: Mapped[dict[str, Any]] = mapped_column(
        "condition_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    action_limit_json: Mapped[dict[str, Any]] = mapped_column(
        "action_limit_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="guardrails")


class ExecutionAuditLog(Base):
    __tablename__ = "execution_audit_logs"
    __table_args__ = (
        Index("ix_execution_audit_logs_user_created", "user_id", "created_at"),
        Index("ix_execution_audit_logs_user_status", "user_id", "status"),
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
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        "payload_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    execution_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    reasoning_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    why_action_taken: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_influenced_json: Mapped[dict[str, Any]] = mapped_column(
        "data_influenced_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    result_json: Mapped[dict[str, Any]] = mapped_column(
        "result_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="success")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="execution_audit_logs")


class MoneyLoopConfig(Base):
    __tablename__ = "money_loop_config"

    user_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_daily_capital: Mapped[float] = mapped_column(Float, nullable=False, default=50000.0)
    max_parallel_missions: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")
    auto_execute: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    optimizer_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="money_loop_configs")


class ResearchProject(Base):
    __tablename__ = "research_projects"
    __table_args__ = (
        Index("ix_research_projects_user_created", "user_id", "created_at"),
        Index("ix_research_projects_user_status", "user_id", "status"),
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
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False, default="general")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    folders_json: Mapped[dict[str, Any]] = mapped_column(
        "folders_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    sources_json: Mapped[dict[str, Any]] = mapped_column(
        "sources_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    notes_json: Mapped[dict[str, Any]] = mapped_column(
        "notes_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    summaries_json: Mapped[dict[str, Any]] = mapped_column(
        "summaries_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    experiments_json: Mapped[dict[str, Any]] = mapped_column(
        "experiments_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    outputs_json: Mapped[dict[str, Any]] = mapped_column(
        "outputs_json",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user: Mapped["User"] = relationship(back_populates="research_projects")
    organization: Mapped["Organization"] = relationship(back_populates="research_projects")


class UserRuntimeConfig(Base):
    """
    Per-user key/value runtime settings (broker keys, feature toggles, trading halt).
    Matches Alembic ``0048_user_runtime_config``.
    """

    __tablename__ = "user_runtime_config"
    __table_args__ = (Index("ix_user_runtime_config_updated_at", "updated_at"),)

    user_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    config_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    config_value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="runtime_configs")


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
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    source_id: Mapped[Optional[int]] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        nullable=True,
    )
    input_data_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    outcome_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    success: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
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


class SecurityAuditLog(Base):
    """Week 1 Day 2: security incidents (failed auth, 403s, rate limits, blocked dangerous routes)."""

    __tablename__ = "security_audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    details: Mapped[dict[str, Any]] = mapped_column(
        "details",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=lambda: {},
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


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


class JarvisEpisode(Base):
    """Episodic Jarvis memory — conversations, ideas, milestones (Living Jarvis Upgrade 1)."""

    __tablename__ = "jarvis_episodes"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    episode_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    importance: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=5)
    embedding: Mapped[Optional[list[Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    user: Mapped["User"] = relationship(back_populates="jarvis_episode_rows")


class JarvisFact(Base):
    """Semantic Jarvis memory — structured preferences and business facts."""

    __tablename__ = "jarvis_facts"
    __table_args__ = (UniqueConstraint("user_id", "fact_type", "key", name="uq_jarvis_facts_user_type_key"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(256), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0.7"))
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="jarvis")
    last_verified: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="jarvis_fact_rows")


class JarvisSession(Base):
    """Working-memory session metadata (client-supplied session id string)."""

    __tablename__ = "jarvis_sessions"
    __table_args__ = (UniqueConstraint("user_id", "session_id", name="uq_jarvis_sessions_user_session"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_active: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    user: Mapped["User"] = relationship(back_populates="jarvis_session_rows")
    turns: Mapped[list["JarvisSessionTurn"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class JarvisSessionTurn(Base):
    """One message in a Jarvis working-memory session."""

    __tablename__ = "jarvis_session_turns"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    session_row_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("jarvis_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    session: Mapped["JarvisSession"] = relationship(back_populates="turns")


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


class JarvisProactiveFeedback(Base):
    """User feedback on proactive alerts — learning loop (Upgrade 2.1)."""

    __tablename__ = "jarvis_proactive_feedback"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alert_dedupe_key: Mapped[str] = mapped_column(String(256), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    meta: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="jarvis_proactive_feedback_rows")


class JarvisGoal(Base):
    """Upgrade 2.2 — user-defined goals the autonomous agent tracks over time."""

    __tablename__ = "jarvis_goals"

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
    goal_type: Mapped[str] = mapped_column(String(64), nullable=False, default="custom")
    description: Mapped[str] = mapped_column(Text, nullable=False)
    target_value: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    deadline: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    progress: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    meta: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="jarvis_goal_rows")
    organization: Mapped[Optional["Organization"]] = relationship()
    subtasks: Mapped[list["JarvisGoalSubtask"]] = relationship(
        back_populates="goal", cascade="all, delete-orphan"
    )


class JarvisGoalSubtask(Base):
    """Steps derived from ``break_into_subtasks`` for a ``JarvisGoal``."""

    __tablename__ = "jarvis_goal_subtasks"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    goal_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("jarvis_goals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    goal: Mapped["JarvisGoal"] = relationship(back_populates="subtasks")


class JarvisDailyAgentPlan(Base):
    """Persisted 'Today's Plan' (business + personal + risks) for the autonomous loop."""

    __tablename__ = "jarvis_daily_agent_plans"
    __table_args__ = (UniqueConstraint("user_id", "plan_date", name="uq_jarvis_daily_agent_plan_user_date"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="jarvis_daily_agent_plan_rows")


class JarvisAgentActionLog(Base):
    """Outcomes of autonomous steps (success / partial / failed) for learning and retries."""

    __tablename__ = "jarvis_agent_action_log"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="jarvis_agent_action_log_rows")


class JarvisAgentEventQueue(Base):
    """DB-backed queue for inventory / meeting / invoice events (Upgrade 2.3)."""

    __tablename__ = "jarvis_agent_event_queue"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    organization_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped[Optional["Organization"]] = relationship()
    user: Mapped[Optional["User"]] = relationship()


class AgentTask(Base):
    """Persisted Jarvis agentic workflow (plan → approve → execute)."""

    __tablename__ = "agent_tasks"
    __table_args__ = (UniqueConstraint("task_id", name="uq_agent_tasks_task_id"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    os_key: Mapped[str] = mapped_column(String(32), nullable=False)
    full_plan_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
    )
    current_step_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    execution_logs: Mapped[list[Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
    )
    correlation_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship()
    organization: Mapped["Organization"] = relationship()


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


class StockPriceAlert(Base):
    """User-defined price / percent-change alerts for real-time stock monitor."""

    __tablename__ = "stock_price_alerts"

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
    condition_type: Mapped[str] = mapped_column(String(24), nullable=False)
    price_threshold: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    reference_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    percent_threshold: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False, default="notify")
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="stock_price_alert_rows")


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


class FinancialAuditLog(Base):
    """
    Immutable append-only financial audit trail.

    Rows must never be deleted by application code (compliance / forensic replay).
    """

    __tablename__ = "financial_audit_logs"

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
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    entity_id: Mapped[Optional[int]] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), nullable=True)
    before_state: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    after_state: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    correlation_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[Optional["User"]] = relationship(back_populates="financial_audit_logs")


class LearningPattern(Base):
    """
    Self-Evolution Phase 1: extracted patterns from ``LearningLog`` with rolling confidence.

    Populated by ``services.ml.learning_pipeline`` (nightly). Read by the brain-health
    endpoint and the self-evolution trigger.
    """

    __tablename__ = "learning_patterns"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    pattern_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    pattern_key: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sample_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=lambda: {}
    )
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "pattern_type", "pattern_key", name="uq_learning_patterns_scope"
        ),
    )


class OutcomeFeedback(Base):
    """
    Self-Evolution Phase 1: predicted vs actual outcome for a single action.

    Used to compute rolling accuracy for ML models and to drive self-evolution triggers.
    """

    __tablename__ = "outcome_feedback"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    model_name: Mapped[str] = mapped_column(String(128), nullable=False, default="", index=True)
    action_id: Mapped[str] = mapped_column(String(128), nullable=False, default="", index=True)
    action_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    predicted_outcome: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=lambda: {}
    )
    actual_outcome: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=lambda: {}
    )
    accuracy_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    learned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class MLModel(Base):
    """
    Self-Evolution Phase 1: registered ML models with version + accuracy tracking.

    Persisted artifacts live at ``model_path`` (a path on disk). Only one row per
    ``(name, version)`` and at most one ``is_active=True`` per ``name`` enforced at
    application level by ``services.ml.model_registry``.
    """

    __tablename__ = "ml_models"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="0.0.1")
    accuracy: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    metrics: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=lambda: {}
    )
    training_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    model_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_ml_models_name_version"),
    )


class EvolutionTrigger(Base):
    """
    Self-Evolution Phase 1: trigger row created when the system detects a condition
    that may justify a self-coder proposal (low accuracy, recurring error, declining metric).

    Lifecycle: ``proposed`` → (``approved`` | ``rejected``) → (``applied`` | ``failed``).
    Owner-only API approves and dispatches to ``services.self_coder_agent.run_pipeline``.
    """

    __tablename__ = "evolution_triggers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trigger_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    proposed_change: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed", index=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=lambda: {}
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class CausalEdge(Base):
    """
    Self-Evolution Phase 2: a directed edge ``cause → effect`` with running mean
    and variance of observed strengths.

    ``observation_count``/``sum_strength``/``sum_strength_sq`` are running statistics
    used by ``services.causal.causal_graph.CausalGraph`` to derive ``strength``
    (mean) and ``confidence`` (1 / (1 + stddev) bounded to [0, 1]) without
    re-aggregating from raw logs.
    """

    __tablename__ = "causal_edges"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    cause_variable: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    effect_variable: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    strength: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sum_strength: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    sum_strength_sq: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    evidence_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=lambda: {}
    )
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "cause_variable",
            "effect_variable",
            name="uq_causal_edges_scope",
        ),
    )


class FeatureArchive(Base):
    """
    Self-Evolution Phase 2: idempotent daily snapshot of a single feature value.

    Unique on ``(organization_id, scope, feature_name, captured_date)`` so a
    daily archive job can be re-run safely.
    """

    __tablename__ = "feature_archive"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    feature_name: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=lambda: {}
    )
    captured_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "scope",
            "feature_name",
            "captured_date",
            name="uq_feature_archive_daily",
        ),
        Index("ix_feature_archive_scope_name", "scope", "feature_name"),
    )


class PredictionPending(Base):
    """
    Self-Evolution Phase 2: a single prediction awaiting outcome resolution
    by ``services.ml.online_learner``.

    Workflow:
        1. ``predict()`` → row created with ``resolved=False`` and
           ``resolve_after = now + horizon``.
        2. After ``resolve_after`` an outcome resolver fills ``actual_outcome``
           and computes ``accuracy_score``, then ``model.partial_fit(...)``.
    """

    __tablename__ = "predictions_pending"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    model_name: Mapped[str] = mapped_column(String(128), nullable=False, default="", index=True)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    action_id: Mapped[str] = mapped_column(String(128), nullable=False, default="", index=True)
    action_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    features_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=lambda: {}
    )
    predicted_outcome: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=lambda: {}
    )
    predicted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolve_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_outcome: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=lambda: {}
    )
    accuracy_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class DomainDefinition(Base):
    """
    Self-Evolution Phase 2: persisted definition of a domain plugin (mirrors the
    in-process ``DomainRegistry``). The registry seeds rows here on boot so new
    deployments can introspect / extend domains without code changes.
    """

    __tablename__ = "domain_definitions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    models: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=lambda: []
    )
    features: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=lambda: []
    )
    tables: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=lambda: []
    )
    prompts: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=lambda: {}
    )
    policies: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=lambda: {}
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("name", name="uq_domain_definitions_name"),)


# Back-compat alias (deprecated)
Org = Organization
