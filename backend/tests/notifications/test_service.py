from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import MonitorChannel, Notification
from app.notifications.service import IncidentSubject, enqueue_notifications
from tests.helpers import make_account, make_incident, make_monitor, make_notification_channel


async def _route(session: AsyncSession, account_id: uuid.UUID, monitor_id: uuid.UUID, channel_id: uuid.UUID) -> None:
    session.add(MonitorChannel(account_id=account_id, monitor_id=monitor_id, channel_id=channel_id))
    await session.flush()


async def test_fans_out_to_verified_routed_channels_only(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    monitor = await make_monitor(db_session, account.id)
    verified = await make_notification_channel(
        db_session, account.id, verified_at=datetime.now(timezone.utc)
    )
    unverified = await make_notification_channel(db_session, account.id, verified_at=None)
    await _route(db_session, account.id, monitor.id, verified.id)
    await _route(db_session, account.id, monitor.id, unverified.id)
    incident = await make_incident(db_session, account.id, monitor_id=monitor.id)
    await db_session.commit()

    count = await enqueue_notifications(
        db_session,
        account.id,
        incident.id,
        IncidentSubject(kind="monitor", id=monitor.id),
        "opened",
        {"cause": "http_status"},
    )
    await db_session.commit()

    assert count == 1
    rows = (await db_session.execute(select(Notification))).scalars().all()
    assert len(rows) == 1
    assert rows[0].channel_id == verified.id
    assert rows[0].event == "opened"


async def test_skips_channels_not_routed_to_this_monitor(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    monitor = await make_monitor(db_session, account.id)
    other_monitor = await make_monitor(db_session, account.id)
    channel = await make_notification_channel(
        db_session, account.id, verified_at=datetime.now(timezone.utc)
    )
    await _route(db_session, account.id, other_monitor.id, channel.id)
    await db_session.commit()

    count = await enqueue_notifications(
        db_session,
        account.id,
        uuid.uuid4(),
        IncidentSubject(kind="monitor", id=monitor.id),
        "opened",
        {},
    )
    await db_session.commit()

    assert count == 0
    assert (await db_session.execute(select(Notification))).first() is None


async def test_zero_channels_inserts_nothing(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    monitor = await make_monitor(db_session, account.id)
    await db_session.commit()

    count = await enqueue_notifications(
        db_session,
        account.id,
        uuid.uuid4(),
        IncidentSubject(kind="monitor", id=monitor.id),
        "opened",
        {},
    )
    await db_session.commit()

    assert count == 0
    assert (await db_session.execute(select(Notification))).first() is None


async def test_rolls_back_together_with_the_caller_transaction(db_session: AsyncSession) -> None:
    """enqueue_notifications must never commit on its own -- it's meant to be called from
    inside the SAME transaction as the incident write, so a rollback there takes the outbox
    rows with it."""
    account = await make_account(db_session)
    monitor = await make_monitor(db_session, account.id)
    channel = await make_notification_channel(
        db_session, account.id, verified_at=datetime.now(timezone.utc)
    )
    await _route(db_session, account.id, monitor.id, channel.id)
    incident = await make_incident(db_session, account.id, monitor_id=monitor.id)
    await db_session.commit()

    count = await enqueue_notifications(
        db_session,
        account.id,
        incident.id,
        IncidentSubject(kind="monitor", id=monitor.id),
        "opened",
        {},
    )
    assert count == 1
    await db_session.rollback()

    assert (await db_session.execute(select(Notification))).first() is None
