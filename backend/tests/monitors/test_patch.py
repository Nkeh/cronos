from __future__ import annotations

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.monitors.models import Monitor
from tests.helpers import login_as

_PAYLOAD = {"name": "api", "url": "http://chaos:8000/health"}


async def _create(client: AsyncClient, csrf_headers: dict) -> dict:
    resp = await client.post("/api/v1/monitors", json=_PAYLOAD, headers=csrf_headers)
    assert resp.status_code == 201
    return resp.json()


async def test_patch_then_get_round_trip(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)
    monitor = await _create(client, csrf_headers)

    patch_resp = await client.patch(
        f"/api/v1/monitors/{monitor['id']}",
        json={"url": "http://chaos:8001/other"},
        headers=csrf_headers,
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["url"] == "http://chaos:8001/other"
    assert patch_resp.json()["status"] == "new"

    get_resp = await client.get(f"/api/v1/monitors/{monitor['id']}")
    assert get_resp.json()["url"] == "http://chaos:8001/other"
    assert get_resp.json()["status"] == "new"


async def test_target_change_resets_status_to_new_when_active(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)
    monitor = await _create(client, csrf_headers)

    resp = await client.patch(
        f"/api/v1/monitors/{monitor['id']}", json={"method": "HEAD"}, headers=csrf_headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "new"


async def test_pause_then_target_change_then_resume_clears_failures_and_ewma(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    """Amendment 3: consecutive_failures/ewma reset unconditionally on a
    target-field PATCH; only `status` follows the pause rule. Resume must
    not resurrect the pre-reset failure/ewma state."""
    await login_as(client, db_session, app.state.clock)
    monitor = await _create(client, csrf_headers)
    monitor_id = monitor["id"]

    pause_resp = await client.post(
        f"/api/v1/monitors/{monitor_id}/pause", json={}, headers=csrf_headers
    )
    assert pause_resp.status_code == 200
    assert pause_resp.json()["status"] == "paused"

    # Seed non-zero failure/ewma state directly, bypassing the API — nothing
    # in v1 writes these columns yet (that's the runner, Day 6+).
    await db_session.execute(
        update(Monitor)
        .where(Monitor.id == monitor_id)
        .values(consecutive_failures=3, ewma_mean=42.0, ewma_var=1.0, ewma_n=5)
    )
    await db_session.commit()

    patch_resp = await client.patch(
        f"/api/v1/monitors/{monitor_id}",
        json={"url": "http://chaos:8002/changed"},
        headers=csrf_headers,
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == "paused"  # pause rule wins over reset-to-new

    row = await db_session.get(Monitor, monitor_id)
    assert row.consecutive_failures == 0
    assert row.ewma_mean is None
    assert row.ewma_var is None
    assert row.ewma_n == 0

    resume_resp = await client.post(
        f"/api/v1/monitors/{monitor_id}/resume", json={}, headers=csrf_headers
    )
    assert resume_resp.status_code == 200
    assert resume_resp.json()["status"] == "new"

    await db_session.refresh(row)
    assert row.consecutive_failures == 0
    assert row.ewma_mean is None
