from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.engine.claim import claim_due_monitors
from app.engine.db_bounds import bounded_transaction
from tests.helpers import make_account, make_monitor

_TOLERANCE = timedelta(seconds=3)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def test_claim_only_due_and_active(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    due = await make_monitor(
        db_session, account.id, next_check_at=_utcnow() - timedelta(seconds=5)
    )
    not_due = await make_monitor(
        db_session, account.id, next_check_at=_utcnow() + timedelta(hours=1)
    )
    paused = await make_monitor(
        db_session,
        account.id,
        next_check_at=_utcnow() - timedelta(seconds=5),
        is_active=False,
        status="paused",
    )
    await db_session.commit()

    claimed = await claim_due_monitors(db_session, free_slots=10)
    await db_session.commit()

    claimed_ids = {c.id for c in claimed}
    assert due.id in claimed_ids
    assert not_due.id not in claimed_ids
    assert paused.id not in claimed_ids


async def test_claim_respects_limit(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    for _ in range(5):
        await make_monitor(db_session, account.id, next_check_at=_utcnow() - timedelta(seconds=5))
    await db_session.commit()

    claimed = await claim_due_monitors(db_session, free_slots=3)
    await db_session.commit()

    assert len(claimed) == 3


async def test_claim_zero_free_slots_claims_nothing(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    await make_monitor(db_session, account.id, next_check_at=_utcnow() - timedelta(seconds=5))
    await db_session.commit()

    assert await claim_due_monitors(db_session, free_slots=0) == []


async def test_claim_orders_by_next_check_at(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    oldest = await make_monitor(
        db_session, account.id, next_check_at=_utcnow() - timedelta(seconds=30)
    )
    middle = await make_monitor(
        db_session, account.id, next_check_at=_utcnow() - timedelta(seconds=20)
    )
    await make_monitor(db_session, account.id, next_check_at=_utcnow() - timedelta(seconds=10))
    await db_session.commit()

    claimed = await claim_due_monitors(db_session, free_slots=2)
    await db_session.commit()

    assert [c.id for c in claimed] == [oldest.id, middle.id]


async def test_cadence_on_time_monitor_keeps_phase(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    old_next_check_at = _utcnow() - timedelta(seconds=1)
    monitor = await make_monitor(
        db_session, account.id, interval_seconds=120, next_check_at=old_next_check_at
    )
    await db_session.commit()

    claimed = await claim_due_monitors(db_session, free_slots=10)
    await db_session.commit()

    assert len(claimed) == 1
    expected = old_next_check_at + timedelta(seconds=120)
    # claim_due_monitors' UPDATE is raw SQL (bypasses the ORM unit-of-work), so `monitor`
    # (already in this session's identity map from make_monitor's flush) needs an explicit
    # refresh to see the new next_check_at.
    await db_session.refresh(monitor)
    assert abs(monitor.next_check_at - expected) < _TOLERANCE


async def test_cadence_late_monitor_skips_missed_slots(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    old_next_check_at = _utcnow() - timedelta(seconds=300)
    monitor = await make_monitor(
        db_session, account.id, interval_seconds=120, next_check_at=old_next_check_at
    )
    await db_session.commit()

    claimed = await claim_due_monitors(db_session, free_slots=10)
    await db_session.commit()

    assert len(claimed) == 1
    await db_session.refresh(monitor)
    # NOT old_next_check_at + 120s (which would still be in the past) -- jumps to now() + 120s.
    expected = _utcnow() + timedelta(seconds=120)
    assert abs(monitor.next_check_at - expected) < _TOLERANCE


async def test_scheduled_for_matches_pre_claim_next_check_at(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    old_next_check_at = _utcnow() - timedelta(seconds=5)
    monitor = await make_monitor(db_session, account.id, next_check_at=old_next_check_at)
    await db_session.commit()

    claimed = await claim_due_monitors(db_session, free_slots=10)
    await db_session.commit()

    assert len(claimed) == 1
    assert abs(claimed[0].scheduled_for - old_next_check_at) < timedelta(seconds=1)
    assert claimed[0].id == monitor.id


async def test_claimed_at_and_claim_monotonic_present(db_session: AsyncSession) -> None:
    """Day 8: every ClaimedMonitor carries a DB-authoritative claimed_at plus a same-process
    monotonic reading, so the state machine can derive a skew-free probe-start timestamp
    without an extra round trip. See app/engine/state.py."""
    account = await make_account(db_session)
    await make_monitor(db_session, account.id, next_check_at=_utcnow() - timedelta(seconds=5))
    await db_session.commit()

    before = time.monotonic()
    claimed = await claim_due_monitors(db_session, free_slots=10)
    after = time.monotonic()
    await db_session.commit()

    assert len(claimed) == 1
    assert abs(claimed[0].claimed_at - _utcnow()) < _TOLERANCE
    assert before <= claimed[0].claim_monotonic <= after


async def test_claim_lock_timeout_gives_up_and_a_later_claim_succeeds(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    """FOR UPDATE SKIP LOCKED never blocks on a locked monitor row by design -- it skips it --
    so a table-level lock is the only thing that actually exercises lock_timeout here."""
    account = await make_account(db_session)
    await make_monitor(db_session, account.id, next_check_at=_utcnow() - timedelta(seconds=5))
    await db_session.commit()

    blocker_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    blocker = blocker_factory()
    # AsyncSession autobegins on first execute -- this holds the table lock open until the
    # rollback() in the finally block below.
    await blocker.execute(text("LOCK TABLE monitors IN SHARE ROW EXCLUSIVE MODE"))

    fast_timeout_settings = get_settings().model_copy(
        update={"runner_claim_lock_timeout_ms": 500}
    )
    try:
        start = asyncio.get_running_loop().time()
        with pytest.raises(DBAPIError):
            async with bounded_transaction(
                db_session,
                lock_timeout_ms=fast_timeout_settings.runner_claim_lock_timeout_ms,
                statement_timeout_ms=fast_timeout_settings.runner_claim_statement_timeout_ms,
            ):
                await claim_due_monitors(db_session, free_slots=10)
        elapsed = asyncio.get_running_loop().time() - start
        assert elapsed < 3, "lock_timeout should have given up well under the test's own ceiling"
    finally:
        await blocker.rollback()
        await blocker.close()

    # The session is usable again (bounded_transaction's session.begin() rolled back on the
    # caught exception) and a subsequent claim, with the lock released, succeeds normally.
    claimed = await claim_due_monitors(db_session, free_slots=10)
    await db_session.commit()
    assert len(claimed) == 1


async def test_two_concurrent_claims_never_double_claim(db_engine: AsyncEngine) -> None:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    setup_session = session_factory()
    account = await make_account(setup_session)
    monitor_ids = []
    for _ in range(200):
        monitor = await make_monitor(
            setup_session,
            account.id,
            next_check_at=_utcnow() - timedelta(seconds=5),
            interval_seconds=30,
        )
        monitor_ids.append(monitor.id)
    await setup_session.commit()
    await setup_session.close()

    async def claim_all(free_slots: int) -> list[uuid.UUID]:
        session = session_factory()
        try:
            claimed = await claim_due_monitors(session, free_slots)
            await session.commit()
            return [c.id for c in claimed]
        finally:
            await session.close()

    results = await asyncio.gather(claim_all(150), claim_all(150))
    all_claimed = results[0] + results[1]

    assert len(all_claimed) == 200
    assert len(set(all_claimed)) == 200
    assert set(all_claimed) == set(monitor_ids)
