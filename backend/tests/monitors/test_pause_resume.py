from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.incidents.models import Incident
from app.monitors.models import Monitor
from app.notifications.models import Notification
from tests.helpers import login_as, make_incident

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


async def test_pause_with_open_incident_resolves_paused_silently(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    user = await login_as(client, db_session, app.state.clock)
    monitor = await _create(client, csrf_headers)
    incident = await make_incident(db_session, user.account_id, monitor_id=monitor["id"])
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/monitors/{monitor['id']}/pause", json={}, headers=csrf_headers
    )
    assert resp.status_code == 200

    # A plain select, not expire_all()+get(): .get()'s expired-primary-key reload path can
    # collide with pool_pre_ping's connection-ping-under-greenlet when reloading a row another
    # connection just mutated (observed as sqlalchemy.exc.MissingGreenlet here specifically).
    incident_row = (
        await db_session.execute(select(Incident).where(Incident.id == incident.id))
    ).scalar_one()
    assert incident_row.resolved_reason == "paused"
    assert incident_row.resolved_at is not None

    notifications = (
        await db_session.execute(
            select(Notification).where(Notification.incident_id == incident.id)
        )
    ).all()
    assert notifications == [], "a pause-resolve must never enqueue a notification"


async def test_resume_does_not_bump_last_state_at(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    """Regression guard for the documented pause/resume vs. edit asymmetry: only a target-field
    PATCH bumps last_state_at (a probe against the OLD target can race an edit on an ACTIVE
    monitor); pause/resume never race an in-flight probe the same way, so resume must leave
    last_state_at exactly as it was."""
    await login_as(client, db_session, app.state.clock)
    monitor = await _create(client, csrf_headers)
    monitor_id = monitor["id"]

    row_before = await db_session.get(Monitor, monitor_id)
    last_state_at_before = row_before.last_state_at

    await client.post(f"/api/v1/monitors/{monitor_id}/pause", json={}, headers=csrf_headers)
    resp = await client.post(f"/api/v1/monitors/{monitor_id}/resume", json={}, headers=csrf_headers)
    assert resp.status_code == 200

    db_session.expire_all()
    row_after = await db_session.get(Monitor, monitor_id)
    assert row_after.last_state_at == last_state_at_before


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
