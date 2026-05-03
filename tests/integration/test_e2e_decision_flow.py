"""
End-to-end integration: login -> POST /chat/decision -> ai_decisions persistence.

External Groq/legacy brain are **not** required: ``DecisionBrainV2.decide`` is stubbed to return a
policy-shaped payload so :mod:`api.routes.ai_chat` exercises PolicyEngine wiring and DB inserts.

Uses an isolated SQLite engine (StaticPool) and patches ``core.database`` session/engine accessors.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import core.database as core_db
from core import permission_engine as permission_engine_mod
from api.routes import ai_chat
from core.auth import hash_password
from core.db.base import Base
from core.db.models import (
    AiDecision,
    Organization,
    RefreshToken,
    Role,
    UsageLog,
    User,
    UserOrganizationMembership,
)
from core.rbac import permissions_for_role
from main import app
from services import audit_log as audit_log_mod


class _FakeDecisionBrainV2:
    """Return a payload compatible with ``_bundle_from_decision_brain_v2``."""

    async def decide(self, **kwargs):  # noqa: ANN003
        return {
            "source": "policy_engine",
            "action": "analyze",
            "confidence": 0.82,
            "reasoning": ["e2e stub: LinUCB analyze arm"],
            "metadata": {"integration": "test_e2e_decision_flow"},
            "action_type": "business",
            "learning_log_id": None,
            "expected_reward": 0.45,
        }


@pytest.fixture
def e2e_sqlite(monkeypatch: pytest.MonkeyPatch) -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        Organization.__table__,
        Role.__table__,
        User.__table__,
        UserOrganizationMembership.__table__,
        RefreshToken.__table__,
        AiDecision.__table__,
        UsageLog.__table__,
    ]
    Base.metadata.create_all(bind=engine, tables=tables)
    factory: sessionmaker[Session] = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    monkeypatch.setenv("SECRET_KEY", "e2e-test-secret-key-minimum-32-chars!!")
    monkeypatch.setenv("JWT_SECRET_KEY", "e2e-test-secret-key-minimum-32-chars!!")
    monkeypatch.setenv("THIRAMAI_AUTH_DISABLED", "0")

    def _perms_cached(*, organization_id: int, role_name: str) -> frozenset[str]:
        """Avoid RBAC m2m tables on minimal SQLite schema (static role permissions only)."""
        return frozenset(permissions_for_role(role_name))

    monkeypatch.setattr(permission_engine_mod, "permissions_for_role_cached", _perms_cached)

    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    monkeypatch.setattr(core_db, "get_session_factory", lambda: factory)

    with factory() as s:
        with s.begin():
            s.add(Organization(id=1, name="E2E Trading Firm", plan="free"))
            s.add(Role(id=1, organization_id=1, name="owner", level=1))
            s.add(
                User(
                    id=1,
                    email="trader@test.com",
                    password_hash=hash_password("testpass123"),
                    name="Test Trader",
                    is_active=True,
                )
            )
            s.add(
                UserOrganizationMembership(
                    user_id=1,
                    organization_id=1,
                    role_id=1,
                    is_active=True,
                )
            )

    monkeypatch.setattr(ai_chat, "get_decision_brain_v2", lambda: _FakeDecisionBrainV2())
    # SQLite DDL in this repo uses JSONB on some audit tables; skip real audit inserts for this harness.
    _noop_audit = lambda **kwargs: None
    monkeypatch.setattr(ai_chat.system_audit, "record_system_audit", _noop_audit)
    monkeypatch.setattr(audit_log_mod, "record_system_audit", _noop_audit)

    yield factory

    app.dependency_overrides.clear()


def test_complete_decision_flow_login_and_chat_decision(e2e_sqlite: sessionmaker[Session]) -> None:
    with TestClient(app) as client:
        login = client.post(
            "/auth/login",
            data={"username": "trader@test.com", "password": "testpass123"},
        )
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]

        dec = client.post(
            "/chat/decision",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "Should I buy RELIANCE for a short-term trade?"},
        )
        assert dec.status_code == 200, dec.text
        body = dec.json()
        assert body.get("ok") is True
        assert body.get("phase") == "decision_engine"
        assert body.get("status") == "pending_approval"
        assert body.get("decision_id") is not None

    with e2e_sqlite() as s:
        rows = list(s.scalars(select(AiDecision).where(AiDecision.organization_id == 1)).all())
        assert len(rows) >= 1
        last = rows[-1]
        assert last.action == "noop"
        assert last.status == "pending"


def test_chat_decision_with_long_message(e2e_sqlite: sessionmaker[Session]) -> None:
    with TestClient(app) as client:
        login = client.post(
            "/auth/login",
            data={"username": "trader@test.com", "password": "testpass123"},
        )
        token = login.json()["access_token"]
        r = client.post(
            "/chat/decision",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "message": "Summarize risk if my tech basket is INFY, TCS, and Wipro equally weighted.",
            },
        )
        assert r.status_code == 200
        assert r.json().get("ok") is True


def test_chat_decision_validation_empty_message(e2e_sqlite: sessionmaker[Session]) -> None:
    with TestClient(app) as client:
        login = client.post(
            "/auth/login",
            data={"username": "trader@test.com", "password": "testpass123"},
        )
        token = login.json()["access_token"]
        r = client.post(
            "/chat/decision",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": ""},
        )
        assert r.status_code == 422


def test_chat_decision_requires_auth(e2e_sqlite: sessionmaker[Session]) -> None:
    with TestClient(app) as client:
        r = client.post("/chat/decision", json={"message": "Unauthorized path probe"})
        assert r.status_code in (401, 403)


def test_policy_engine_decision_smoke() -> None:
    from services.policy_engine import DecisionContext, PolicyEngine

    pe = PolicyEngine()
    out = pe.decide(DecisionContext(intent="e2e_probe", domain="business", user_id=1, organization_id=1))
    assert out.action
    assert 0.0 <= out.confidence <= 1.0


def test_decision_router_route_surface() -> None:
    from services.decision_router import DecisionRouter

    r = DecisionRouter()
    assert hasattr(r, "route")
    assert callable(r.route)
    assert r.policy_engine is not None
