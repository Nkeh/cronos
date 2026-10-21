from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.notifications.models import Notification, NotificationAttempt
from app.notifier.claim import ClaimedNotification
from app.notifier.outcomes import DeliveryOutcome
from app.notifier.record import record_outcome
from tests.helpers import make_account, make_notification, make_notification_channel, utcnow


def _claimed(notification: Notification, *, attempts: int) -> ClaimedNotification:
    return ClaimedNotification(
        id=notification.id,
        account_id=notification.account_id,
        incident_id=notification.incident_id,
        channel_id=notification.channel_id,
        event=notification.event,
        payload=notification.payload,
        attempts=attempts,
    )


async def _setup(db_session: AsyncSession, **overrides: object) -> Notification:
    account = await make_account(db_session)
    channel = await make_notification_channel(db_session, account.id, verified_at=utcnow())
    notification = await make_notification(db_session, account.id, channel.id, **overrides)
    await db_session.commit()
    return notification


async def test_sent_outcome_marks_sent_and_records_attempt(db_session: AsyncSession) -> None:
    notification = await _setup(db_session, attempts=1)
    await record_outcome(
        db_session, _claimed(notification, attempts=1), DeliveryOutcome(outcome="sent"),
        get_settings(), duration_ms=42,
    )
    await db_session.commit()

    await db_session.refresh(notification)
    assert notification.status == "sent"
    assert notification.sent_at is not None
    assert notification.last_error is None

    attempts = (
        await db_session.execute(
            select(NotificationAttempt).where(NotificationAttempt.notification_id == notification.id)
        )
    ).scalars().all()
    assert len(attempts) == 1
    assert attempts[0].outcome == "sent"
    assert attempts[0].duration_ms == 42


async def test_failed_outcome_is_terminal_with_no_retry(db_session: AsyncSession) -> None:
    notification = await _setup(db_session, attempts=1)
    await record_outcome(
        db_session, _claimed(notification, attempts=1),
        DeliveryOutcome(outcome="failed", status_code=404, error="not found"),
        get_settings(), duration_ms=10,
    )
    await db_session.commit()

    await db_session.refresh(notification)
    assert notification.status == "failed"
    assert notification.last_error == "not found"


async def test_retry_outcome_schedules_the_next_backoff_step(db_session: AsyncSession) -> None:
    settings = get_settings()
    notification = await _setup(db_session, attempts=1)
    before = utcnow()

    await record_outcome(
        db_session, _claimed(notification, attempts=1),
        DeliveryOutcome(outcome="retry", status_code=500, error="server error"),
        settings, duration_ms=10,
    )
    await db_session.commit()

    await db_session.refresh(notification)
    assert notification.status == "pending"
    expected_delay = settings.notifier_backoff_seconds_list[0]
    assert abs((notification.next_attempt_at - before).total_seconds() - expected_delay) < 5


async def test_retry_outcome_at_max_attempts_becomes_permanently_failed(db_session: AsyncSession) -> None:
    settings = get_settings()
    notification = await _setup(db_session, attempts=settings.notifier_max_attempts)

    await record_outcome(
        db_session, _claimed(notification, attempts=settings.notifier_max_attempts),
        DeliveryOutcome(outcome="retry", status_code=500, error="server error"),
        settings, duration_ms=10,
    )
    await db_session.commit()

    await db_session.refresh(notification)
    assert notification.status == "failed"


async def test_retry_after_header_is_honoured_over_the_fixed_backoff(db_session: AsyncSession) -> None:
    settings = get_settings()
    notification = await _setup(db_session, attempts=1)
    before = utcnow()

    await record_outcome(
        db_session, _claimed(notification, attempts=1),
        DeliveryOutcome(outcome="retry", status_code=429, retry_after_seconds=17),
        settings, duration_ms=10,
    )
    await db_session.commit()

    await db_session.refresh(notification)
    assert abs((notification.next_attempt_at - before).total_seconds() - 17) < 5


async def test_retry_after_header_is_capped_at_one_hour(db_session: AsyncSession) -> None:
    settings = get_settings()
    notification = await _setup(db_session, attempts=1)
    before = utcnow()

    await record_outcome(
        db_session, _claimed(notification, attempts=1),
        DeliveryOutcome(outcome="retry", status_code=429, retry_after_seconds=999_999),
        settings, duration_ms=10,
    )
    await db_session.commit()

    await db_session.refresh(notification)
    delay = (notification.next_attempt_at - before).total_seconds()
    assert abs(delay - 3600) < 5


async def test_suppressed_outcome_sets_status_with_no_attempt_row(db_session: AsyncSession) -> None:
    notification = await _setup(db_session, attempts=1)
    await record_outcome(
        db_session, _claimed(notification, attempts=1), DeliveryOutcome(outcome="suppressed"),
        get_settings(), duration_ms=0,
    )
    await db_session.commit()

    await db_session.refresh(notification)
    assert notification.status == "suppressed"
    attempts = (
        await db_session.execute(
            select(NotificationAttempt).where(NotificationAttempt.notification_id == notification.id)
        )
    ).scalars().all()
    assert attempts == []
