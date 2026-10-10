from __future__ import annotations

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.monitors.models import Monitor
from app.status_pages.models import StatusPage, StatusPageItem
from tests.helpers import make_account, make_monitor, make_status_page


async def test_status_page_slug_format(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    with pytest.raises(IntegrityError):
        await make_status_page(db_session, account.id, slug="Not Valid!")
    await db_session.rollback()


async def test_status_page_requires_token_when_private(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    with pytest.raises(IntegrityError):
        await make_status_page(db_session, account.id, is_public=False, access_token_hash=None)
    await db_session.rollback()


async def test_private_status_page_with_token_succeeds(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    page = await make_status_page(
        db_session, account.id, is_public=False, access_token_hash="hashed"
    )
    assert page.is_public is False


async def test_item_exactly_one_subject(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    page = await make_status_page(db_session, account.id)
    await db_session.commit()

    db_session.add(
        StatusPageItem(
            status_page_id=page.id,
            account_id=account.id,
            monitor_id=None,
            heartbeat_id=None,
            display_name="x",
            position=1,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_duplicate_monitor_on_same_page_rejected(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    page = await make_status_page(db_session, account.id)
    monitor = await make_monitor(db_session, account.id)
    await db_session.commit()

    db_session.add(
        StatusPageItem(
            status_page_id=page.id,
            account_id=account.id,
            monitor_id=monitor.id,
            display_name="first",
            position=1,
        )
    )
    await db_session.commit()

    db_session.add(
        StatusPageItem(
            status_page_id=page.id,
            account_id=account.id,
            monitor_id=monitor.id,
            display_name="dup",
            position=2,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_deferred_position_swap_succeeds_at_commit(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    page = await make_status_page(db_session, account.id)
    monitor_1 = await make_monitor(db_session, account.id)
    monitor_2 = await make_monitor(db_session, account.id)
    item_1 = StatusPageItem(
        status_page_id=page.id, account_id=account.id, monitor_id=monitor_1.id,
        display_name="a", position=1,
    )
    item_2 = StatusPageItem(
        status_page_id=page.id, account_id=account.id, monitor_id=monitor_2.id,
        display_name="b", position=2,
    )
    db_session.add_all([item_1, item_2])
    await db_session.commit()

    # Swap positions in one transaction — momentarily colliding on item_1's
    # new position=2 (item_2 still holds it until its own UPDATE runs).
    # Deferred means neither statement raises; only COMMIT checks uniqueness.
    await db_session.execute(
        update(StatusPageItem).where(StatusPageItem.id == item_1.id).values(position=2)
    )
    await db_session.execute(
        update(StatusPageItem).where(StatusPageItem.id == item_2.id).values(position=1)
    )
    await db_session.commit()  # proves the swap actually committed clean


async def test_deferred_position_constraint_still_catches_real_duplicate_at_commit(
    db_session: AsyncSession,
) -> None:
    account = await make_account(db_session)
    page = await make_status_page(db_session, account.id)
    monitor_1 = await make_monitor(db_session, account.id)
    monitor_2 = await make_monitor(db_session, account.id)
    db_session.add(
        StatusPageItem(
            status_page_id=page.id, account_id=account.id, monitor_id=monitor_1.id,
            display_name="a", position=1,
        )
    )
    await db_session.commit()

    db_session.add(
        StatusPageItem(
            status_page_id=page.id, account_id=account.id, monitor_id=monitor_2.id,
            display_name="b", position=1,  # genuine, unresolved duplicate
        )
    )
    await db_session.flush()  # deferred — does not raise here

    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_deleting_status_page_cascades_items(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    page = await make_status_page(db_session, account.id)
    monitor = await make_monitor(db_session, account.id)
    item = StatusPageItem(
        status_page_id=page.id, account_id=account.id, monitor_id=monitor.id,
        display_name="a", position=1,
    )
    db_session.add(item)
    await db_session.commit()  # flushes item.id via RETURNING before we capture it
    page_id, item_id = page.id, item.id

    await db_session.delete(await db_session.get(StatusPage, page_id))
    await db_session.commit()
    db_session.expire_all()

    assert await db_session.get(StatusPageItem, item_id) is None


async def test_deleting_monitor_removes_only_its_item_not_the_page(
    db_session: AsyncSession,
) -> None:
    account = await make_account(db_session)
    page = await make_status_page(db_session, account.id)
    monitor = await make_monitor(db_session, account.id)
    item = StatusPageItem(
        status_page_id=page.id, account_id=account.id, monitor_id=monitor.id,
        display_name="a", position=1,
    )
    db_session.add(item)
    await db_session.commit()  # flushes item.id via RETURNING before we capture it
    monitor_id, item_id, page_id = monitor.id, item.id, page.id

    await db_session.delete(await db_session.get(Monitor, monitor_id))
    await db_session.commit()
    db_session.expire_all()

    assert await db_session.get(StatusPageItem, item_id) is None
    assert await db_session.get(StatusPage, page_id) is not None
