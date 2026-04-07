"""Phase 4: JWT / retail-sale guard / per-user rate limit on ``POST /chat/query``."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.dependencies import CurrentUser, get_current_user
from core.auth import create_access_token
from core.brain_output import ActionIntentNone, BrainStructuredResponse
import core.rate_limit_middleware as rlm
from main import app


@pytest.fixture(autouse=True)
def _security_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-phase4-security-tests")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-phase4-security-tests")
    monkeypatch.setenv("THIRAMAI_AUTH_DISABLED", "0")
    monkeypatch.setenv("THIRAMAI_RL_CHAT_QUERY_PER_USER_PER_MINUTE", "5")
    with rlm._RL_LOCK:
        rlm._HITS.clear()


@pytest.fixture(autouse=True)
def _clear_overrides() -> None:
    yield
    app.dependency_overrides.clear()


def test_chat_query_401_without_bearer() -> None:
    client = TestClient(app)
    r = client.post("/chat/query", json={"message": "Hello"})
    assert r.status_code == 401
    assert r.json().get("detail")


def test_chat_query_401_expired_jwt() -> None:
    token = create_access_token(
        sub_user_id=1,
        org_id=1,
        role_name="staff",
        expires_delta=timedelta(minutes=-10),
    )
    client = TestClient(app)
    r = client.post(
        "/chat/query",
        json={"message": "Hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401
    assert "expired" in str(r.json().get("detail", "")).lower()


def test_chat_query_401_invalid_jwt() -> None:
    client = TestClient(app)
    r = client.post(
        "/chat/query",
        json={"message": "Hello"},
        headers={"Authorization": "Bearer not-a-valid-jwt"},
    )
    assert r.status_code == 401


def test_chat_query_403_customer_sell_phrase() -> None:
    async def _customer() -> CurrentUser:
        return CurrentUser(
            id=99,
            email="cust@test.local",
            organization_id=1,
            role_name="customer",
            role_level=5,
            is_active=True,
        )

    app.dependency_overrides[get_current_user] = _customer
    token = create_access_token(sub_user_id=99, org_id=1, role_name="customer")
    client = TestClient(app)
    r = client.post(
        "/chat/query",
        json={"message": "Sell 2 units of DemoSKU"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
    assert "staff" in str(r.json().get("detail", "")).lower() or "admin" in str(
        r.json().get("detail", "")
    ).lower()


def test_chat_query_429_after_five_requests_same_user() -> None:
    async def _staff() -> CurrentUser:
        return CurrentUser(
            id=42,
            email="staff@test.local",
            organization_id=1,
            role_name="staff",
            role_level=4,
            is_active=True,
        )

    app.dependency_overrides[get_current_user] = _staff
    token = create_access_token(sub_user_id=42, org_id=1, role_name="staff")
    stub = BrainStructuredResponse(narrative="stub", action_intent=ActionIntentNone())

    client = TestClient(app)
    with (
        patch("api.routes.ai_chat.run_brain", return_value=stub),
        patch("api.routes.ai_chat.asset_portal.drain_new_index_rows_for_organization", return_value=[]),
    ):
        for _ in range(5):
            r = client.post(
                "/chat/query",
                json={"message": "What is our stock status?"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 200, r.text
        r6 = client.post(
            "/chat/query",
            json={"message": "What is our stock status?"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r6.status_code == 429
    body = r6.json()
    assert body.get("bucket") == "chat_query_user" or "limit" in str(body).lower()


def test_sell_stock_model_rejects_negative_quantity() -> None:
    from core.brain_output import parse_action_intent_dict

    with pytest.raises(ValidationError):
        parse_action_intent_dict(
            {"kind": "sell_stock", "sku_name": "X", "quantity": -5, "location": ""}
        )
