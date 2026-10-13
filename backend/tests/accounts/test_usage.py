from __future__ import annotations

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.plans.config import get_plan
from tests.helpers import login_as, make_api_key, make_heartbeat, make_monitor, make_status_page


async def test_usage_counts_and_limits(
    client: AsyncClient, db_session: AsyncSession, app: FastAPI
) -> None:
    user = await login_as(client, db_session, app.state.clock)
    await make_monitor(db_session, user.account_id)
    await make_monitor(db_session, user.account_id)
    await make_heartbeat(db_session, user.account_id)
    await make_status_page(db_session, user.account_id)
    await make_api_key(db_session, user.account_id, created_by_user_id=user.id)
    await make_api_key(
        db_session, user.account_id, created_by_user_id=user.id, revoked_at=app.state.clock.now()
    )
    await db_session.commit()

    resp = await client.get("/api/v1/usage")
    assert resp.status_code == 200
    body = resp.json()

    assert body["plan"] == "launch"
    assert body["launch_period"] is True
    assert body["counts"] == {
        "monitors": 2,
        "heartbeats": 1,
        "status_pages": 1,
        "api_keys": 1,  # revoked key excluded
    }

    plan = get_plan("launch")
    assert body["limits"]["max_monitors"] == plan.max_monitors
    assert body["limits"]["max_api_keys"] == plan.max_api_keys
    assert "name" not in body["limits"]


async def test_usage_works_without_email_verification(
    client: AsyncClient, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock, verified=False)
    resp = await client.get("/api/v1/usage")
    assert resp.status_code == 200
