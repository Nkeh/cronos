"""Day 9, confirmed with Oryn: a brand-new monitor auto-routes to every is_default channel on
the account at creation time, same transaction as the insert. Monitor<->channel routing's own
GET/PUT sub-resource endpoints are exercised in tests/notifications/test_router.py (channels is
the API surface that owns the broader routing behavior); this file is scoped to the creation hook.
"""

from __future__ import annotations

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import MonitorChannel
from tests.helpers import login_as, make_notification_channel

_PAYLOAD = {"name": "api", "url": "http://chaos:8000/health"}


async def test_create_monitor_auto_routes_to_every_default_channel(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    user = await login_as(client, db_session, app.state.clock)
    default_channel = await make_notification_channel(db_session, user.account_id, is_default=True)
    non_default_channel = await make_notification_channel(db_session, user.account_id, is_default=False)
    await db_session.commit()

    resp = await client.post("/api/v1/monitors", json=_PAYLOAD, headers=csrf_headers)
    assert resp.status_code == 201
    monitor_id = resp.json()["id"]

    routed = (
        await db_session.execute(
            select(MonitorChannel.channel_id).where(MonitorChannel.monitor_id == monitor_id)
        )
    ).scalars().all()
    assert routed == [default_channel.id]
    assert non_default_channel.id not in routed


async def test_create_monitor_with_no_default_channels_routes_to_nothing(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)

    resp = await client.post("/api/v1/monitors", json=_PAYLOAD, headers=csrf_headers)
    assert resp.status_code == 201
    monitor_id = resp.json()["id"]

    routed = (
        await db_session.execute(
            select(MonitorChannel.channel_id).where(MonitorChannel.monitor_id == monitor_id)
        )
    ).scalars().all()
    assert routed == []


async def test_create_monitor_routes_to_multiple_default_channels(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    user = await login_as(client, db_session, app.state.clock)
    first = await make_notification_channel(db_session, user.account_id, is_default=True)
    second = await make_notification_channel(
        db_session, user.account_id, is_default=True, kind="webhook", config={"url": "http://chaos:8000/webhook"}
    )
    await db_session.commit()

    resp = await client.post("/api/v1/monitors", json=_PAYLOAD, headers=csrf_headers)
    monitor_id = resp.json()["id"]

    routed = set(
        (
            await db_session.execute(
                select(MonitorChannel.channel_id).where(MonitorChannel.monitor_id == monitor_id)
            )
        )
        .scalars()
        .all()
    )
    assert routed == {first.id, second.id}
