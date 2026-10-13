from __future__ import annotations

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.monitors.models import Monitor
from tests.helpers import login_as

_PAYLOAD = {"name": "api", "url": "http://chaos:8000/health"}


async def _create(client: AsyncClient, csrf_headers: dict) -> dict:
    resp = await client.post("/api/v1/monitors", json=_PAYLOAD, headers=csrf_headers)
    assert resp.status_code == 201
    return resp.json()


async def test_pause_sets_is_active_false_and_status_paused(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)
    monitor = await _create(client, csrf_headers)

    resp = await client.post(
        f"/api/v1/monitors/{monitor['id']}/pause", json={}, headers=csrf_headers
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False
    assert resp.json()["status"] == "paused"

    row = await db_session.get(Monitor, monitor["id"])
    assert row.is_active is False
    assert row.status == "paused"


async def test_resume_sets_is_active_true_status_new_and_resets_failures(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)
    monitor = await _create(client, csrf_headers)
    monitor_id = monitor["id"]

    await client.post(f"/api/v1/monitors/{monitor_id}/pause", json={}, headers=csrf_headers)
    resp = await client.post(f"/api/v1/monitors/{monitor_id}/resume", json={}, headers=csrf_headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True
    assert resp.json()["status"] == "new"
    assert resp.json()["next_check_at"] is not None

    row = await db_session.get(Monitor, monitor_id)
    assert row.is_active is True
    assert row.status == "new"
    assert row.consecutive_failures == 0


async def test_check_now_sets_next_check_at_to_now(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)
    monitor = await _create(client, csrf_headers)
    monitor_id = monitor["id"]

    before = (await db_session.execute(text("SELECT now()"))).scalar_one()

    resp = await client.post(
        f"/api/v1/monitors/{monitor_id}/check-now", json={}, headers=csrf_headers
    )
    assert resp.status_code == 204

    row = await db_session.get(Monitor, monitor_id)
    await db_session.refresh(row)
    assert row.next_check_at >= before


async def test_check_now_on_paused_monitor_is_409(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)
    monitor = await _create(client, csrf_headers)
    monitor_id = monitor["id"]

    await client.post(f"/api/v1/monitors/{monitor_id}/pause", json={}, headers=csrf_headers)

    resp = await client.post(
        f"/api/v1/monitors/{monitor_id}/check-now", json={}, headers=csrf_headers
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "monitor_paused"
