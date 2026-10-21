from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.maintenance import run_flapping_exit_sweep
from app.monitors.models import Monitor
from app.notifications.models import MonitorChannel, Notification
from tests.helpers import make_account, make_incident, make_monitor, make_notification_channel, utcnow


async def _flapping_monitor(db_session: AsyncSession, **overrides: object) -> Monitor:
    account = await make_account(db_session)
    defaults: dict[str, object] = {"status": "up", "flapping_since": utcnow() - timedelta(minutes=5)}
    defaults.update(overrides)
    monitor = await make_monitor(db_session, account.id, **defaults)
    channel = await make_notification_channel(db_session, account.id, verified_at=utcnow())
    db_session.add(MonitorChannel(account_id=account.id, monitor_id=monitor.id, channel_id=channel.id))
    await db_session.commit()
    return monitor


async def test_clears_flapping_since_once_stable_and_enqueues_one_ended_notice(
    db_session: AsyncSession,
) -> None:
    monitor = await _flapping_monitor(db_session)

    result = await run_flapping_exit_sweep(db_session, stable_minutes=1)
    await db_session.commit()

    assert result.lock_acquired is True
    assert result.monitors_cleared == 1

    await db_session.refresh(monitor)
    assert monitor.flapping_since is None

    rows = (await db_session.execute(select(Notification))).scalars().all()
    assert len(rows) == 1
    assert rows[0].event == "flapping"
    assert rows[0].payload["phase"] == "ended"


async def test_does_not_clear_when_an_incident_started_within_the_stable_window(
    db_session: AsyncSession,
) -> None:
    monitor = await _flapping_monitor(db_session)
    account_id = monitor.account_id
    await make_incident(db_session, account_id, monitor_id=monitor.id, started_at=utcnow())
    await db_session.commit()

    result = await run_flapping_exit_sweep(db_session, stable_minutes=30)
    await db_session.commit()

    assert result.monitors_cleared == 0
    await db_session.refresh(monitor)
    assert monitor.flapping_since is not None


async def test_does_not_clear_a_monitor_that_is_still_down(db_session: AsyncSession) -> None:
    monitor = await _flapping_monitor(db_session, status="down")

    result = await run_flapping_exit_sweep(db_session, stable_minutes=1)
    await db_session.commit()

    assert result.monitors_cleared == 0
    await db_session.refresh(monitor)
    assert monitor.flapping_since is not None


async def test_running_twice_in_a_row_is_idempotent(db_session: AsyncSession) -> None:
    await _flapping_monitor(db_session)

    first = await run_flapping_exit_sweep(db_session, stable_minutes=1)
    await db_session.commit()
    second = await run_flapping_exit_sweep(db_session, stable_minutes=1)
    await db_session.commit()

    assert first.monitors_cleared == 1
    assert second.monitors_cleared == 0

    rows = (await db_session.execute(select(Notification))).scalars().all()
    assert len(rows) == 1  # the second run found nothing left to clear, no duplicate notice
