from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.engine.claim import ClaimedMonitor
from app.engine.db_bounds import bounded_transaction
from app.engine.probe import ProbeResult
from app.engine.state import apply_check_result
from app.incidents.models import Incident
from app.monitors.models import CheckResult, Monitor
from app.notifications.models import MonitorChannel, Notification
from tests.helpers import make_account, make_monitor, make_notification_channel, utcnow

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
            async with bounded_transaction(
                session,
                lock_timeout_ms=settings.runner_claim_lock_timeout_ms,
                statement_timeout_ms=settings.runner_claim_statement_timeout_ms,
            ):
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


# ---- Day 9 / FR-6.3 flapping ----


async def _routed_monitor(db_session: AsyncSession, **monitor_overrides: object) -> Monitor:
    account = await make_account(db_session)
    monitor = await make_monitor(db_session, account.id, confirm_threshold=1, **monitor_overrides)
    channel = await make_notification_channel(db_session, account.id, verified_at=utcnow())
    db_session.add(MonitorChannel(account_id=account.id, monitor_id=monitor.id, channel_id=channel.id))
    await db_session.commit()
    return monitor


async def _down_up_cycle(db_session: AsyncSession, claimed: ClaimedMonitor, t: datetime) -> None:
    await apply_check_result(
        db_session, claimed, _DOWN, probe_started_at=t, suppressed=False, recheck_delay_seconds=30,
        flap_window_minutes=30, flap_threshold=3,
    )
    await db_session.commit()
    await apply_check_result(
        db_session, claimed, _UP, probe_started_at=t + timedelta(seconds=1), suppressed=False,
        recheck_delay_seconds=30, flap_window_minutes=30, flap_threshold=3,
    )
    await db_session.commit()


async def test_third_incident_in_the_window_enters_flapping_and_skips_the_opened_notice(
    db_session: AsyncSession,
) -> None:
    monitor = await _routed_monitor(db_session)
    claimed = _claimed_for(monitor)
    t0 = utcnow()

    await _down_up_cycle(db_session, claimed, t0)
    await _down_up_cycle(db_session, claimed, t0 + timedelta(seconds=10))

    rows = (await db_session.execute(select(Notification))).scalars().all()
    assert sorted(r.event for r in rows) == ["opened", "opened", "resolved", "resolved"]

    # Third incident in the window: crosses flap_threshold=3 -- flapping_since set, exactly one
    # 'flapping' (started) notice, the normal 'opened' notice for THIS incident is skipped.
    outcome3 = await apply_check_result(
        db_session, claimed, _DOWN, probe_started_at=t0 + timedelta(seconds=20),
        suppressed=False, recheck_delay_seconds=30, flap_window_minutes=30, flap_threshold=3,
    )
    await db_session.commit()
    assert outcome3.incident_opened_id is not None

    await db_session.refresh(monitor)
    assert monitor.flapping_since is not None

    rows = (await db_session.execute(select(Notification))).scalars().all()
    assert sorted(r.event for r in rows) == ["flapping", "opened", "opened", "resolved", "resolved"]
    flapping_rows = [r for r in rows if r.event == "flapping"]
    assert len(flapping_rows) == 1
    assert flapping_rows[0].payload["phase"] == "started"
    assert flapping_rows[0].incident_id is None


async def test_while_flapping_further_opens_and_resolves_are_silent(
    db_session: AsyncSession,
) -> None:
    monitor = await _routed_monitor(db_session)
    claimed = _claimed_for(monitor)
    t0 = utcnow()

    await _down_up_cycle(db_session, claimed, t0)
    await _down_up_cycle(db_session, claimed, t0 + timedelta(seconds=10))
    await apply_check_result(
        db_session, claimed, _DOWN, probe_started_at=t0 + timedelta(seconds=20),
        suppressed=False, recheck_delay_seconds=30, flap_window_minutes=30, flap_threshold=3,
    )
    await db_session.commit()
    before = (await db_session.execute(select(Notification))).scalars().all()
    assert len(before) == 5  # 2 opened + 2 resolved + 1 flapping(started)

    # Resolve, then open a 4th incident -- both silent while still flapping.
    await apply_check_result(
        db_session, claimed, _UP, probe_started_at=t0 + timedelta(seconds=21),
        suppressed=False, recheck_delay_seconds=30, flap_window_minutes=30, flap_threshold=3,
    )
    await db_session.commit()
    await apply_check_result(
        db_session, claimed, _DOWN, probe_started_at=t0 + timedelta(seconds=22),
        suppressed=False, recheck_delay_seconds=30, flap_window_minutes=30, flap_threshold=3,
    )
    await db_session.commit()

    after = (await db_session.execute(select(Notification))).scalars().all()
    assert len(after) == 5

    await db_session.refresh(monitor)
    assert monitor.flapping_since is not None


async def test_current_open_incident_acked_guard_suppresses_the_flapping_started_notice(
    db_session: AsyncSession,
) -> None:
    """FR-5.4's ack guard: the entry code checks whether the incident it JUST opened is already
    acknowledged before firing the 'started' notice. In the current call graph that incident
    can't have been acked yet (nothing can acknowledge an incident before it exists) -- this
    test exercises the guard's own SQL directly, proving it reads back true/false correctly, as
    documented in app/engine/state.py's _CURRENT_OPEN_INCIDENT_ACKED_SQL comment."""
    from app.engine.state import _CURRENT_OPEN_INCIDENT_ACKED_SQL

    account = await make_account(db_session)
    monitor = await make_monitor(db_session, account.id, confirm_threshold=1)
    await db_session.commit()
    claimed = _claimed_for(monitor)

    outcome = await apply_check_result(
        db_session, claimed, _DOWN, probe_started_at=utcnow(), suppressed=False,
        recheck_delay_seconds=30,
    )
    await db_session.commit()
    assert outcome.incident_opened_id is not None

    not_acked = (
        await db_session.execute(_CURRENT_OPEN_INCIDENT_ACKED_SQL, {"monitor_id": monitor.id})
    ).scalar_one()
    assert not_acked is False

    incident = await db_session.get(Incident, outcome.incident_opened_id)
    incident.acknowledged_at = utcnow()
    await db_session.commit()

    acked = (
        await db_session.execute(_CURRENT_OPEN_INCIDENT_ACKED_SQL, {"monitor_id": monitor.id})
    ).scalar_one()
    assert acked is True

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
