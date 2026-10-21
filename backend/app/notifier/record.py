"""Turns one DeliveryOutcome into the notifications/notification_attempts writes from the Day 9
plan's outcome table. Runs inside its own bounded_transaction, opened AFTER the send/no-send
decision -- no network I/O happens in here.
"""

from __future__ import annotations

from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.notifications.models import Notification, NotificationAttempt
from app.notifier.claim import ClaimedNotification
from app.notifier.outcomes import DeliveryOutcome


async def record_outcome(
    session: AsyncSession,
    claimed: ClaimedNotification,
    outcome: DeliveryOutcome,
    settings: Settings,
    duration_ms: int,
) -> None:
    if outcome.outcome == "suppressed":
        # No delivery was attempted at all -- no notification_attempts row (see the module
        # docstring in app/notifier/caps.py: the cap_reached enqueue already explains why).
        await session.execute(
            update(Notification).where(Notification.id == claimed.id).values(status="suppressed")
        )
        return

    session.add(
        NotificationAttempt(
            notification_id=claimed.id,
            outcome=outcome.outcome,
            status_code=outcome.status_code,
            error=outcome.error,
            duration_ms=duration_ms,
        )
    )

    if outcome.outcome == "sent":
        await session.execute(
            update(Notification)
            .where(Notification.id == claimed.id)
            .values(status="sent", sent_at=text("now()"), last_error=None)
        )
        return

    if outcome.outcome == "failed":
        await session.execute(
            update(Notification)
            .where(Notification.id == claimed.id)
            .values(status="failed", last_error=outcome.error)
        )
        return

    # outcome == "retry". attempts was already incremented at claim time, so attempts==1 is the
    # first delivery try -- the 5th (notifier_max_attempts) failing retryably is terminal.
    if claimed.attempts >= settings.notifier_max_attempts:
        await session.execute(
            update(Notification)
            .where(Notification.id == claimed.id)
            .values(status="failed", last_error=outcome.error)
        )
        return

    backoff_schedule = settings.notifier_backoff_seconds_list
    backoff_index = min(claimed.attempts - 1, len(backoff_schedule) - 1)
    delay_seconds = (
        outcome.retry_after_seconds
        if outcome.retry_after_seconds is not None
        else backoff_schedule[backoff_index]
    )
    delay_seconds = min(delay_seconds, 3600)
    await session.execute(
        update(Notification)
        .where(Notification.id == claimed.id)
        .values(
            status="pending",
            next_attempt_at=text("now() + make_interval(secs => :delay)").bindparams(
                delay=delay_seconds
            ),
            last_error=outcome.error,
        )
    )
