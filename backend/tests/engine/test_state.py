from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.engine.claim import ClaimedMonitor
from app.engine.db_bounds import bounded_transaction
from app.engine.probe import ProbeResult
from app.engine.state import apply_check_result
from app.incidents.models import Incident
from app.monitors.models import CheckResult, Monitor
from tests.helpers import make_account, make_monitor, utcnow

_TOLERANCE = timedelta(seconds=2)

_UP = ProbeResult(is_up=True, status_code=200, response_time_ms=10, error=None)
_DOWN = ProbeResult(
    is_up=False, status_code=503, response_time_ms=10, error="boom", error_kind="http_status"
)


def _claimed_for(monitor: Monitor) -> ClaimedMonitor:
    now = utcnow()
    return ClaimedMonitor(
        id=monitor.id,
        url=monitor.url,
        method=monitor.method,
        expected_status=monitor.expected_status,
        timeout_seconds=monitor.timeout_seconds,
        scheduled_for=now,
        claimed_at=now,
        claim_monotonic=0.0,
    )


async def test_blip_schedules_recheck_no_incident_counter_reset(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    # next_check_at starts far in the future, simulating claim_due_monitors having already
    # advanced it to the next cadence slot before a probe ever runs. apply_check_result's
    # LEAST-based recheck must pull it *earlier* to now()+recheck_delay_seconds -- if it were
    # left at its just-created default (effectively "now"), LEAST would (correctly, per
    # correction 3) leave it untouched, and this test would be asserting the wrong thing.
    far_future = utcnow() + timedelta(seconds=120)
    monitor = await make_monitor(
        db_session, account.id, confirm_threshold=3, next_check_at=far_future
    )
    await db_session.commit()
    claimed = _claimed_for(monitor)

    t0 = utcnow()
    outcome = await apply_check_result(
        db_session, claimed, _DOWN, probe_started_at=t0, suppressed=False, recheck_delay_seconds=30
    )
    await db_session.commit()
    assert outcome.incident_opened_id is None

    await db_session.refresh(monitor)
    assert monitor.consecutive_failures == 1
    assert monitor.failing_since is not None
    expected_recheck = t0 + timedelta(seconds=30)
    assert abs(monitor.next_check_at - expected_recheck) < _TOLERANCE

    t1 = t0 + timedelta(seconds=5)
    outcome2 = await apply_check_result(
        db_session, claimed, _UP, probe_started_at=t1, suppressed=False, recheck_delay_seconds=30
    )
    await db_session.commit()
    assert outcome2.incident_opened_id is None
    assert outcome2.incident_resolved_id is None

    await db_session.refresh(monitor)
    assert monitor.consecutive_failures == 0
    assert monitor.failing_since is None
    assert monitor.status == "up"


async def test_incident_started_at_uses_first_failure_probe_time(
    db_session: AsyncSession,
) -> None:
    account = await make_account(db_session)
    # last_state_at starts well in the past so both backdated probe_started_at values below
    # register as "fresh" against it -- this test is about the ordering of the two failures
    # relative to EACH OTHER, not about the monitor's creation-time watermark.
    monitor = await make_monitor(
        db_session, account.id, confirm_threshold=2, last_state_at=utcnow() - timedelta(hours=1)
    )
    await db_session.commit()
    claimed = _claimed_for(monitor)

    t0 = utcnow() - timedelta(seconds=40)
    await apply_check_result(
        db_session, claimed, _DOWN, probe_started_at=t0, suppressed=False, recheck_delay_seconds=30
    )
    await db_session.commit()

    t1 = utcnow() - timedelta(seconds=10)
    outcome = await apply_check_result(
        db_session, claimed, _DOWN, probe_started_at=t1, suppressed=False, recheck_delay_seconds=30
    )
    await db_session.commit()

    assert outcome.incident_opened_id is not None
    incident = await db_session.get(Incident, outcome.incident_opened_id)
    assert incident is not None
    # started_at must be the FIRST failure's probe time (t0), never the second's (t1) and
    # never write-time now().
    assert abs((incident.started_at - t0).total_seconds()) < 1
    assert incident.confirmed_at is not None
    assert incident.confirmed_at > incident.started_at
    assert incident.cause == "http_status"


async def test_recovery_resolves_recovered(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    monitor = await make_monitor(db_session, account.id, confirm_threshold=1)
    await db_session.commit()
    claimed = _claimed_for(monitor)

    t0 = utcnow()
    outcome1 = await apply_check_result(
        db_session, claimed, _DOWN, probe_started_at=t0, suppressed=False, recheck_delay_seconds=30
    )
    await db_session.commit()
    assert outcome1.incident_opened_id is not None

    t1 = t0 + timedelta(seconds=5)
    outcome2 = await apply_check_result(
        db_session, claimed, _UP, probe_started_at=t1, suppressed=False, recheck_delay_seconds=30
    )
    await db_session.commit()
    assert outcome2.incident_resolved_id == outcome1.incident_opened_id

    incident = await db_session.get(Incident, outcome1.incident_opened_id)
    assert incident is not None
    assert incident.resolved_reason == "recovered"
    assert incident.resolved_at is not None


async def test_confirm_threshold_one_opens_immediately_no_recheck_bump(
    db_session: AsyncSession,
) -> None:
    account = await make_account(db_session)
    original_next_check_at = utcnow() + timedelta(seconds=120)
    monitor = await make_monitor(
        db_session, account.id, confirm_threshold=1, next_check_at=original_next_check_at
    )
    await db_session.commit()
    claimed = _claimed_for(monitor)

    outcome = await apply_check_result(
        db_session,
        claimed,
        _DOWN,
        probe_started_at=utcnow(),
        suppressed=False,
        recheck_delay_seconds=30,
    )
    await db_session.commit()

    assert outcome.incident_opened_id is not None
    await db_session.refresh(monitor)
    assert abs(monitor.next_check_at - original_next_check_at) < timedelta(milliseconds=50)


async def test_concurrent_threshold_crossings_produce_one_incident(
    db_engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    setup = session_factory()
    account = await make_account(setup)
    monitor = await make_monitor(setup, account.id, confirm_threshold=1)
    await setup.commit()
    monitor_id = monitor.id
    await setup.close()

    settings = get_settings()

    async def _apply() -> None:
        session = session_factory()
        try:
            claimed = ClaimedMonitor(
                id=monitor_id,
                url="https://example.com/",
                method="GET",
                expected_status="2xx",
                timeout_seconds=10,
                scheduled_for=utcnow(),
                claimed_at=utcnow(),
                claim_monotonic=0.0,
            )
            async with bounded_transaction(session, settings):
                await apply_check_result(
                    session,
                    claimed,
                    _DOWN,
                    probe_started_at=utcnow(),
                    suppressed=False,
                    recheck_delay_seconds=30,
                )
        finally:
            await session.close()

    await asyncio.gather(_apply(), _apply())

    verify = session_factory()
    try:
        count = (
            await verify.execute(
                select(Incident).where(Incident.monitor_id == monitor_id)
            )
        ).all()
        assert len(count) == 1
    finally:
        await verify.close()


async def test_stale_result_changes_no_state(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    monitor = await make_monitor(db_session, account.id, confirm_threshold=2)
    await db_session.commit()
    claimed = _claimed_for(monitor)

    t_now = utcnow()
    await apply_check_result(
        db_session, claimed, _UP, probe_started_at=t_now, suppressed=False, recheck_delay_seconds=30
    )
    await db_session.commit()
    await db_session.refresh(monitor)
    last_checked_before = monitor.last_checked_at
    consecutive_before = monitor.consecutive_failures

    stale_probe_time = t_now - timedelta(seconds=10)
    outcome = await apply_check_result(
        db_session,
        claimed,
        _DOWN,
        probe_started_at=stale_probe_time,
        suppressed=False,
        recheck_delay_seconds=30,
    )
    await db_session.commit()
    assert outcome.written is True
    assert outcome.incident_opened_id is None

    await db_session.refresh(monitor)
    assert monitor.consecutive_failures == consecutive_before
    assert monitor.last_checked_at > last_checked_before

    rows = (
        await db_session.execute(select(CheckResult).where(CheckResult.monitor_id == monitor.id))
    ).scalars().all()
    assert len(rows) == 2
    assert any(r.is_up is False for r in rows), "the stale result is still written as evidence"


async def test_in_order_results_both_apply(db_session: AsyncSession) -> None:
    """A result at t0 applied first, then one at t0+0.5s applied right after -- the second must
    not be judged stale against the watermark the first just set."""
    account = await make_account(db_session)
    monitor = await make_monitor(db_session, account.id, confirm_threshold=5)
    await db_session.commit()
    claimed = _claimed_for(monitor)

    t0 = utcnow()
    await apply_check_result(
        db_session, claimed, _DOWN, probe_started_at=t0, suppressed=False, recheck_delay_seconds=30
    )
    await db_session.commit()
    await db_session.refresh(monitor)
    assert monitor.consecutive_failures == 1

    t1 = t0 + timedelta(seconds=0.5)
    await apply_check_result(
        db_session, claimed, _DOWN, probe_started_at=t1, suppressed=False, recheck_delay_seconds=30
    )
    await db_session.commit()
    await db_session.refresh(monitor)
    assert monitor.consecutive_failures == 2


async def test_recheck_never_pushes_an_earlier_schedule_later(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    monitor = await make_monitor(db_session, account.id, confirm_threshold=3)
    await db_session.commit()
    claimed = _claimed_for(monitor)

    # Simulates a concurrent check-now landing between claim and this write.
    now_ts = (await db_session.execute(text("SELECT now()"))).scalar_one()
    await db_session.execute(
        update(Monitor).where(Monitor.id == monitor.id).values(next_check_at=now_ts)
    )
    await db_session.commit()

    await apply_check_result(
        db_session,
        claimed,
        _DOWN,
        probe_started_at=utcnow(),
        suppressed=False,
        recheck_delay_seconds=30,
    )
    await db_session.commit()

    await db_session.refresh(monitor)
    assert monitor.next_check_at <= now_ts + timedelta(seconds=1)


async def test_suppressed_result_touches_nothing_but_check_results(
    db_session: AsyncSession,
) -> None:
    account = await make_account(db_session)
    monitor = await make_monitor(db_session, account.id, confirm_threshold=2)
    await db_session.commit()
    claimed = _claimed_for(monitor)

    outcome = await apply_check_result(
        db_session,
        claimed,
        _DOWN,
        probe_started_at=utcnow(),
        suppressed=True,
        recheck_delay_seconds=30,
    )
    await db_session.commit()
    assert outcome.written is True
    assert outcome.incident_opened_id is None

    await db_session.refresh(monitor)
    assert monitor.consecutive_failures == 0
    assert monitor.failing_since is None

    row = (
        await db_session.execute(select(CheckResult).where(CheckResult.monitor_id == monitor.id))
    ).scalar_one()
    assert row.suppressed is True
    assert row.is_up is False


async def test_paused_mid_flight_writes_nothing(db_engine: AsyncEngine) -> None:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    session = session_factory()
    account = await make_account(session)
    monitor = await make_monitor(session, account.id)
    await session.commit()
    claimed = _claimed_for(monitor)

    pauser = session_factory()
    monitor_row = await pauser.get(Monitor, monitor.id)
    monitor_row.is_active = False
    monitor_row.status = "paused"
    await pauser.commit()
    await pauser.close()

    outcome = await apply_check_result(
        session, claimed, _UP, probe_started_at=utcnow(), suppressed=False, recheck_delay_seconds=30
    )
    await session.commit()

    assert outcome.written is False
    rows = (
        await session.execute(select(CheckResult).where(CheckResult.monitor_id == monitor.id))
    ).all()
    assert rows == []
    await session.close()
