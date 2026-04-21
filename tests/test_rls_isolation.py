from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from core.database import get_engine, tenant_session_scope


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL is required for RLS integration test")
def test_rls_tenant_isolation_with_session_context() -> None:
    engine = get_engine()
    if engine is None:
        pytest.skip("Database engine unavailable")
    if engine.dialect.name != "postgresql":
        pytest.skip("RLS test requires PostgreSQL")

    table = "rls_test_isolation"
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL row_security = off"))
        conn.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))
        conn.execute(
            text(
                f"""
                CREATE TABLE "{table}" (
                    id BIGSERIAL PRIMARY KEY,
                    organization_id BIGINT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
        conn.execute(text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))
        conn.execute(
            text(
                f"""
                CREATE POLICY tenant_isolation ON "{table}"
                USING (
                    organization_id = current_setting('app.current_org_id', true)::bigint
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                INSERT INTO "{table}" (organization_id, payload)
                VALUES
                    (101, 'org_a_row_1'),
                    (101, 'org_a_row_2'),
                    (202, 'org_b_row_1')
                """
            )
        )

    try:
        with tenant_session_scope(101) as session:
            rows = session.execute(
                text(f'SELECT payload FROM "{table}" ORDER BY id')
            ).scalars().all()
            cross = session.execute(
                text(f'SELECT payload FROM "{table}" WHERE organization_id = 202')
            ).scalars().all()
            assert rows == ["org_a_row_1", "org_a_row_2"]
            assert cross == []

        with tenant_session_scope(202) as session:
            rows = session.execute(
                text(f'SELECT payload FROM "{table}" ORDER BY id')
            ).scalars().all()
            assert rows == ["org_b_row_1"]
    finally:
        with engine.begin() as conn:
            conn.execute(text("SET LOCAL row_security = off"))
            conn.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))
