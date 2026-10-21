from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.notifier.caps import is_over_cap
from app.plans.config import get_plan
from tests.helpers import make_account, make_notification, make_notification_channel, utcnow


async def test_under_cap_is_false(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    channel = await make_notification_channel(db_session, account.id, verified_at=utcnow())
    await make_notification(db_session, account.id, channel.id, status="sent", sent_at=utcnow())
    await db_session.commit()

    assert await is_over_cap(db_session, account.id, "email") is False


async def test_at_cap_is_true(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    channel = await make_notification_channel(db_session, account.id, verified_at=utcnow())
    limit = get_plan(account.plan).alert_emails_per_day
    for _ in range(limit):
        await make_notification(db_session, account.id, channel.id, status="sent", sent_at=utcnow())
    await db_session.commit()

    assert await is_over_cap(db_session, account.id, "email") is True


async def test_only_counts_sent_rows_today(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    channel = await make_notification_channel(db_session, account.id, verified_at=utcnow())
    limit = get_plan(account.plan).alert_emails_per_day
    for _ in range(limit):
        await make_notification(db_session, account.id, channel.id, status="pending")
    await db_session.commit()

    assert await is_over_cap(db_session, account.id, "email") is False


async def test_kinds_are_counted_independently(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    email_channel = await make_notification_channel(db_session, account.id, verified_at=utcnow())
    webhook_channel = await make_notification_channel(
        db_session, account.id, kind="webhook", verified_at=utcnow()
    )
    limit = get_plan(account.plan).alert_emails_per_day
    for _ in range(limit):
        await make_notification(
            db_session, account.id, email_channel.id, status="sent", sent_at=utcnow()
        )
    await db_session.commit()

    assert await is_over_cap(db_session, account.id, "email") is True
    assert await is_over_cap(db_session, account.id, "webhook") is False
    assert webhook_channel.kind == "webhook"
