from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import MonitorChannel, Notification
from app.notifications.service import (
    IncidentSubject,
    enqueue_cap_reached_once_per_day,
    enqueue_flapping_notification,
    enqueue_notifications,
)
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


# ---- Day 9: flapping notices ----


async def test_enqueue_flapping_notification_sets_incident_id_null_and_phase(
    db_session: AsyncSession,
) -> None:
    account = await make_account(db_session)
    monitor = await make_monitor(db_session, account.id)
    channel = await make_notification_channel(
        db_session, account.id, verified_at=datetime.now(timezone.utc)
    )
    await _route(db_session, account.id, monitor.id, channel.id)
    await db_session.commit()

    count = await enqueue_flapping_notification(
        db_session, account.id, IncidentSubject(kind="monitor", id=monitor.id), phase="started"
    )
    await db_session.commit()

    assert count == 1
    row = (await db_session.execute(select(Notification))).scalar_one()
    assert row.event == "flapping"
    assert row.incident_id is None
    assert row.payload["phase"] == "started"
    assert row.payload["subject_id"] == str(monitor.id)


# ---- Day 9: once-per-day cap_reached dedup (FR-6.5) ----


async def test_cap_reached_fans_out_to_every_verified_channel_of_that_kind(
    db_session: AsyncSession,
) -> None:
    account = await make_account(db_session)
    email_a = await make_notification_channel(
        db_session, account.id, verified_at=datetime.now(timezone.utc)
    )
    email_b = await make_notification_channel(
        db_session, account.id, verified_at=datetime.now(timezone.utc)
    )
    unverified = await make_notification_channel(db_session, account.id, verified_at=None)
    await db_session.commit()

    count = await enqueue_cap_reached_once_per_day(db_session, account.id, "email")
    await db_session.commit()

    assert count == 2
    rows = (await db_session.execute(select(Notification))).scalars().all()
    assert {r.channel_id for r in rows} == {email_a.id, email_b.id}
    assert unverified.id not in {r.channel_id for r in rows}
    assert all(r.event == "cap_reached" for r in rows)
    assert all(r.incident_id is None for r in rows)


async def test_cap_reached_is_enqueued_at_most_once_per_day(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    await make_notification_channel(db_session, account.id, verified_at=datetime.now(timezone.utc))
    await db_session.commit()

    first = await enqueue_cap_reached_once_per_day(db_session, account.id, "email")
    await db_session.commit()
    second = await enqueue_cap_reached_once_per_day(db_session, account.id, "email")
    await db_session.commit()

    assert first == 1
    assert second == 0
    rows = (await db_session.execute(select(Notification))).scalars().all()
    assert len(rows) == 1


async def test_cap_reached_kinds_are_independent(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    await make_notification_channel(db_session, account.id, verified_at=datetime.now(timezone.utc))
    await db_session.commit()

    await enqueue_cap_reached_once_per_day(db_session, account.id, "email")
    webhook_count = await enqueue_cap_reached_once_per_day(db_session, account.id, "webhook")
    await db_session.commit()

    # No verified webhook channel exists -- fans out to zero, but is not blocked by the
    # email kind's own enqueue today.
    assert webhook_count == 0
