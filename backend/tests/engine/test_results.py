from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.engine.claim import claim_due_monitors
from app.engine.probe import ProbeResult
from app.engine.results import write_result
from app.monitors.models import CheckResult, Monitor
from tests.helpers import make_account, make_monitor

_UP_RESULT = ProbeResult(is_up=True, status_code=200, response_time_ms=123, error=None)


async def test_write_result_inserts_check_result(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    monitor = await make_monitor(
        db_session, account.id, next_check_at=datetime.now(timezone.utc) - timedelta(seconds=5)
    )
    await db_session.commit()

    claimed = await claim_due_monitors(db_session, free_slots=10)
    await db_session.commit()
    assert len(claimed) == 1

    written = await write_result(db_session, claimed[0], _UP_RESULT)
    await db_session.commit()

    assert written is True
    row = (
        await db_session.execute(select(CheckResult).where(CheckResult.monitor_id == monitor.id))
    ).scalar_one()
    assert row.is_up is True
    assert row.response_time_ms == 123
    assert row.scheduled_for == claimed[0].scheduled_for

    # write_result's UPDATE is raw SQL (bypasses the ORM unit-of-work), so the `monitor`
    # instance already in this session's identity map (from make_monitor's flush) won't pick
    # up the new last_checked_at without an explicit refresh.
    await db_session.refresh(monitor)
    assert monitor.last_checked_at is not None


async def test_write_result_mid_flight_pause_writes_nothing(
    db_engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    session = session_factory()
    account = await make_account(session)
    monitor = await make_monitor(
        session, account.id, next_check_at=datetime.now(timezone.utc) - timedelta(seconds=5)
    )
    await session.commit()

    claimed = await claim_due_monitors(session, free_slots=10)
    await session.commit()
    assert len(claimed) == 1

    # Paused in a separate, already-committed session -- simulating the user pausing the
    # monitor while the probe (not modeled here) is still in flight.
    pauser = session_factory()
    monitor_row = await pauser.get(Monitor, monitor.id)
    monitor_row.is_active = False
    monitor_row.status = "paused"
    await pauser.commit()
    await pauser.close()

    written = await write_result(session, claimed[0], _UP_RESULT)
    await session.commit()

    assert written is False
    count = (
        await session.execute(select(CheckResult).where(CheckResult.monitor_id == monitor.id))
    ).all()
    assert count == []
    await session.close()


async def test_write_result_mid_flight_delete_writes_nothing(
    db_engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    session = session_factory()
    account = await make_account(session)
    monitor = await make_monitor(
        session, account.id, next_check_at=datetime.now(timezone.utc) - timedelta(seconds=5)
    )
    await session.commit()

    claimed = await claim_due_monitors(session, free_slots=10)
    await session.commit()
    assert len(claimed) == 1

    deleter = session_factory()
    monitor_row = await deleter.get(Monitor, monitor.id)
    await deleter.delete(monitor_row)
    await deleter.commit()
    await deleter.close()

    written = await write_result(session, claimed[0], _UP_RESULT)
    await session.commit()

    assert written is False
    await session.close()
