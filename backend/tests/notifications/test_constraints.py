from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import MonitorChannel, Notification, NotificationChannel
from tests.helpers import make_account, make_incident, make_monitor, make_notification_channel


async def test_notification_channel_kind_check(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    db_session.add(NotificationChannel(account_id=account.id, kind="carrier_pigeon", config={}))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_webhook_channel_requires_secret(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    with pytest.raises(IntegrityError):
        await make_notification_channel(
            db_session, account.id, kind="webhook", config={"url": "https://example.com"}
        )
    await db_session.rollback()


async def test_webhook_channel_with_secret_succeeds(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    channel = await make_notification_channel(
        db_session,
        account.id,
        kind="webhook",
        config={"url": "https://example.com"},
        secret=b"shh",
    )
    assert channel.secret == b"shh"


async def test_cross_account_monitor_channel_link_fails(db_session: AsyncSession) -> None:
    account_a = await make_account(db_session)
    account_b = await make_account(db_session)
    monitor = await make_monitor(db_session, account_a.id)
    channel = await make_notification_channel(db_session, account_b.id)
    await db_session.commit()

    # monitor belongs to account_a, channel belongs to account_b — linking
    # them under either account_id has no matching composite FK row.
    db_session.add(
        MonitorChannel(monitor_id=monitor.id, channel_id=channel.id, account_id=account_a.id)
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_same_account_monitor_channel_link_succeeds(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    monitor = await make_monitor(db_session, account.id)
    channel = await make_notification_channel(db_session, account.id)
    await db_session.commit()

    db_session.add(
        MonitorChannel(monitor_id=monitor.id, channel_id=channel.id, account_id=account.id)
    )
    await db_session.flush()


@pytest.mark.parametrize(
    "overrides",
    [
        {"event": "not_a_real_event"},
        {"status": "not_a_real_status"},
        {"attempts": -1},
    ],
    ids=["event", "status", "attempts_nonneg"],
)
async def test_notification_check_violations(db_session: AsyncSession, overrides: dict) -> None:
    account = await make_account(db_session)
    channel = await make_notification_channel(db_session, account.id)
    await db_session.commit()

    defaults = {"account_id": account.id, "channel_id": channel.id, "event": "opened"}
    defaults.update(overrides)
    db_session.add(Notification(**defaults))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_cap_reached_notification_without_incident_succeeds(
    db_session: AsyncSession,
) -> None:
    account = await make_account(db_session)
    channel = await make_notification_channel(db_session, account.id)
    await db_session.commit()

    db_session.add(
        Notification(
            account_id=account.id,
            channel_id=channel.id,
            incident_id=None,
            event="cap_reached",
        )
    )
    await db_session.flush()


async def test_notification_incident_must_belong_to_same_account(
    db_session: AsyncSession,
) -> None:
    account_a = await make_account(db_session)
    account_b = await make_account(db_session)
    monitor = await make_monitor(db_session, account_a.id)
    incident = await make_incident(db_session, account_a.id, monitor_id=monitor.id)
    channel = await make_notification_channel(db_session, account_b.id)
    await db_session.commit()

    db_session.add(
        Notification(
            account_id=account_b.id,
            channel_id=channel.id,
            incident_id=incident.id,
            event="opened",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_deleting_channel_cascades_notifications(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    channel = await make_notification_channel(db_session, account.id)
    await db_session.commit()

    notification = Notification(
        account_id=account.id, channel_id=channel.id, event="cap_reached"
    )
    db_session.add(notification)
    await db_session.commit()
    channel_id, notification_id = channel.id, notification.id

    await db_session.delete(await db_session.get(NotificationChannel, channel_id))
    await db_session.commit()
    db_session.expire_all()

    assert await db_session.get(Notification, notification_id) is None
