from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.notifier.claim import claim_due_notifications, oldest_pending_age_seconds
from tests.helpers import make_account, make_notification, make_notification_channel, utcnow


async def _channel(db_session: AsyncSession) -> tuple:
    account = await make_account(db_session)
    channel = await make_notification_channel(db_session, account.id, verified_at=utcnow())
    return account, channel


async def test_claims_a_due_pending_row(db_session: AsyncSession) -> None:
    account, channel = await _channel(db_session)
    notification = await make_notification(db_session, account.id, channel.id)
    await db_session.commit()

    claimed = await claim_due_notifications(db_session, free_slots=10, lease_seconds=60)
    await db_session.commit()

    assert [c.id for c in claimed] == [notification.id]
    assert claimed[0].attempts == 1

    await db_session.refresh(notification)
    assert notification.status == "sending"
    assert notification.attempts == 1
    assert notification.next_attempt_at > utcnow()


async def test_does_not_claim_a_not_yet_due_pending_row(db_session: AsyncSession) -> None:
    account, channel = await _channel(db_session)
    await make_notification(
        db_session, account.id, channel.id, next_attempt_at=utcnow() + timedelta(minutes=5)
    )
    await db_session.commit()

    claimed = await claim_due_notifications(db_session, free_slots=10, lease_seconds=60)
    await db_session.commit()

    assert claimed == []


async def test_reclaims_an_expired_sending_lease(db_session: AsyncSession) -> None:
    """A row stuck in 'sending' past its own next_attempt_at (the notifier died mid-delivery)
    looks exactly like a pending row and is reclaimed, with attempts incremented again -- the
    documented at-least-once behavior."""
    account, channel = await _channel(db_session)
    notification = await make_notification(
        db_session,
        account.id,
        channel.id,
        status="sending",
        attempts=1,
        next_attempt_at=utcnow() - timedelta(seconds=5),
    )
    await db_session.commit()

    claimed = await claim_due_notifications(db_session, free_slots=10, lease_seconds=60)
    await db_session.commit()

    assert [c.id for c in claimed] == [notification.id]
    assert claimed[0].attempts == 2

    await db_session.refresh(notification)
    assert notification.status == "sending"
    assert notification.attempts == 2


async def test_does_not_reclaim_a_live_sending_lease(db_session: AsyncSession) -> None:
    account, channel = await _channel(db_session)
    await make_notification(
        db_session,
        account.id,
        channel.id,
        status="sending",
        attempts=1,
        next_attempt_at=utcnow() + timedelta(seconds=30),
    )
    await db_session.commit()

    claimed = await claim_due_notifications(db_session, free_slots=10, lease_seconds=60)
    await db_session.commit()

    assert claimed == []


async def test_respects_free_slots_limit(db_session: AsyncSession) -> None:
    account, channel = await _channel(db_session)
    for _ in range(5):
        await make_notification(db_session, account.id, channel.id)
    await db_session.commit()

    claimed = await claim_due_notifications(db_session, free_slots=2, lease_seconds=60)
    await db_session.commit()

    assert len(claimed) == 2


async def test_zero_free_slots_claims_nothing_and_skips_the_query(db_session: AsyncSession) -> None:
    account, channel = await _channel(db_session)
    await make_notification(db_session, account.id, channel.id)
    await db_session.commit()

    claimed = await claim_due_notifications(db_session, free_slots=0, lease_seconds=60)
    assert claimed == []


async def test_never_claims_sent_or_failed_or_suppressed_rows(db_session: AsyncSession) -> None:
    account, channel = await _channel(db_session)
    for terminal_status in ("sent", "failed", "suppressed"):
        await make_notification(
            db_session,
            account.id,
            channel.id,
            status=terminal_status,
            next_attempt_at=utcnow() - timedelta(seconds=5),
        )
    await db_session.commit()

    claimed = await claim_due_notifications(db_session, free_slots=10, lease_seconds=60)
    await db_session.commit()

    assert claimed == []


async def test_oldest_pending_age_is_none_when_nothing_pending(db_session: AsyncSession) -> None:
    assert await oldest_pending_age_seconds(db_session) is None


async def test_oldest_pending_age_reports_seconds_since_the_oldest_row(
    db_session: AsyncSession,
) -> None:
    account, channel = await _channel(db_session)
    await make_notification(
        db_session, account.id, channel.id, created_at=utcnow() - timedelta(seconds=120)
    )
    await db_session.commit()

    age = await oldest_pending_age_seconds(db_session)
    assert age is not None
    assert age >= 110
