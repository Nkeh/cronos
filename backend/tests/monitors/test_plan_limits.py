from __future__ import annotations

import asyncio

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.monitors.models import Monitor
from app.plans.config import get_plan
from tests.helpers import login_as


async def test_interval_below_plan_minimum_is_plan_limited(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)

    resp = await client.post(
        "/api/v1/monitors",
        json={"name": "too-fast", "url": "http://chaos:8000/health", "interval_seconds": 60},
        headers=csrf_headers,
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "plan_limit"
    assert body["error"]["field"] == "interval_seconds"


async def test_sixteenth_monitor_is_plan_limited(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)
    max_monitors = get_plan("launch").max_monitors

    for i in range(max_monitors):
        resp = await client.post(
            "/api/v1/monitors",
            json={"name": f"m{i}", "url": f"http://chaos:8000/{i}"},
            headers=csrf_headers,
        )
        assert resp.status_code == 201

    over_limit = await client.post(
        "/api/v1/monitors",
        json={"name": "one-too-many", "url": "http://chaos:8000/over"},
        headers=csrf_headers,
    )
    assert over_limit.status_code == 422
    assert over_limit.json()["error"]["code"] == "plan_limit"
    assert "field" not in over_limit.json()["error"]


async def test_twenty_parallel_creates_from_ten_existing_yields_exactly_fifteen(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    """Correctness rides entirely on check_limit's account-row FOR UPDATE
    lock, taken only in the route's final short block — not on any test-side
    serialization."""
    user = await login_as(client, db_session, app.state.clock)
    max_monitors = get_plan("launch").max_monitors

    for i in range(10):
        resp = await client.post(
            "/api/v1/monitors",
            json={"name": f"existing-{i}", "url": f"http://chaos:8000/existing-{i}"},
            headers=csrf_headers,
        )
        assert resp.status_code == 201

    async def _create(i: int):
        return await client.post(
            "/api/v1/monitors",
            json={"name": f"race-{i}", "url": f"http://chaos:8000/race-{i}"},
            headers=csrf_headers,
        )

    responses = await asyncio.gather(*(_create(i) for i in range(20)))
    succeeded = [r for r in responses if r.status_code == 201]
    rejected = [r for r in responses if r.status_code == 422]
    assert len(succeeded) == 5
    assert len(rejected) == 15
    assert all(r.json()["error"]["code"] == "plan_limit" for r in rejected)

    total = (
        await db_session.execute(select(Monitor).where(Monitor.account_id == user.account_id))
    ).scalars().all()
    assert len(total) == max_monitors
