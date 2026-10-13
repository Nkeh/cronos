from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.monitors.models import Monitor
from app.plans.config import get_plan
from app.plans.downgrade import apply_plan_limits
from app.status_pages.models import StatusPage
from tests.helpers import make_account, make_heartbeat, make_monitor, make_status_page

_BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _at(i: int) -> datetime:
    # Explicit, strictly increasing created_at per row — relying on
    # Postgres's own now() would give every row in the same uncommitted
    # transaction an IDENTICAL timestamp (now() is transaction-stable, not
    # per-statement), making "newest first" undefined.
    return _BASE_TIME + timedelta(seconds=i)


async def test_pauses_newest_surplus_monitors_and_heartbeats(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    plan = get_plan("launch")

    monitors = [
        await make_monitor(db_session, account.id, name=f"m{i}", created_at=_at(i))
        for i in range(plan.max_monitors + 3)
    ]
    heartbeats = [
        await make_heartbeat(db_session, account.id, name=f"h{i}", created_at=_at(i))
        for i in range(plan.max_heartbeats + 2)
    ]
    await db_session.commit()

    report = await apply_plan_limits(db_session, account.id, plan)
    await db_session.commit()

    assert len(report.paused_monitor_ids) == 3
    assert len(report.paused_heartbeat_ids) == 2

    newest_monitor_ids = {m.id for m in sorted(monitors, key=lambda m: m.created_at, reverse=True)[:3]}
    assert set(report.paused_monitor_ids) == newest_monitor_ids
    newest_heartbeat_ids = {
        h.id for h in sorted(heartbeats, key=lambda h: h.created_at, reverse=True)[:2]
    }
    assert set(report.paused_heartbeat_ids) == newest_heartbeat_ids

    remaining_active = (
        (
            await db_session.execute(
                select(Monitor).where(
                    Monitor.account_id == account.id, Monitor.is_active.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(remaining_active) == plan.max_monitors


async def test_raises_intervals_below_minimum(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    plan = get_plan("launch")
    low = await make_monitor(db_session, account.id, interval_seconds=60)
    ok = await make_monitor(db_session, account.id, interval_seconds=300)
    await db_session.commit()

    report = await apply_plan_limits(db_session, account.id, plan)
    await db_session.commit()

    assert report.raised_interval_monitor_ids == [low.id]
    await db_session.refresh(low)
    await db_session.refresh(ok)
    assert low.interval_seconds == plan.min_interval_seconds
    assert ok.interval_seconds == 300


async def test_unpublishes_newest_surplus_status_pages(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    plan = get_plan("launch")
    run_id = uuid.uuid4().hex[:8]
    pages = [
        await make_status_page(
            db_session, account.id, slug=f"page-{run_id}-{i}", created_at=_at(i)
        )
        for i in range(plan.max_status_pages + 2)
    ]
    await db_session.commit()

    report = await apply_plan_limits(db_session, account.id, plan)
    await db_session.commit()

    newest_page_ids = {p.id for p in sorted(pages, key=lambda p: p.created_at, reverse=True)[:2]}
    assert set(report.unpublished_status_page_ids) == newest_page_ids

    for page_id in report.unpublished_status_page_ids:
        page = await db_session.get(StatusPage, page_id)
        assert page.is_public is False
        assert page.access_token_hash is not None  # CHECK requires one once private

    remaining_public = (
        (
            await db_session.execute(
                select(StatusPage).where(
                    StatusPage.account_id == account.id, StatusPage.is_public.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(remaining_public) == plan.max_status_pages


async def test_deletes_nothing(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    plan = get_plan("launch")
    for i in range(plan.max_monitors + 5):
        await make_monitor(db_session, account.id, name=f"m{i}", created_at=_at(i))
    await db_session.commit()

    before = (
        (await db_session.execute(select(Monitor).where(Monitor.account_id == account.id)))
        .scalars()
        .all()
    )

    await apply_plan_limits(db_session, account.id, plan)
    await db_session.commit()

    after = (
        (await db_session.execute(select(Monitor).where(Monitor.account_id == account.id)))
        .scalars()
        .all()
    )
    assert len(before) == len(after)
