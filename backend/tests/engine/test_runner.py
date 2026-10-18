from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.redis import FailOpenRedis
from app.engine.claim import ClaimedMonitor, claim_due_monitors
from app.engine.http_probe import HttpProbe
from app.engine.probe import ProbeResult, StubProbe
from app.engine.runner import (
    _build_default_probe,
    _maybe_schedule_canary_round,
    _RunnerContext,
    _run_one,
    _spawn,
    on_tick,
)
from app.monitors.models import CheckResult, Monitor
from tests.helpers import make_account, make_monitor


class _DelayByMonitor:
    """ctx.probe is shared mutable state read only once each task actually runs -- reassigning
    it between two back-to-back _spawn calls (with no await between them) doesn't give either
    task "its own" probe, since asyncio.create_task doesn't start either coroutine until the
    next suspension point, by which time both assignments have already happened. This probe
    looks up the delay by monitor id instead, so each task genuinely gets its own timing."""

    def __init__(self, delays_ms: dict[uuid.UUID, int]) -> None:
        self._delays_ms = delays_ms

    async def check(self, claimed: ClaimedMonitor) -> ProbeResult:
        delay_ms = self._delays_ms[claimed.id]
        await asyncio.sleep(delay_ms / 1000)
        return ProbeResult(is_up=True, status_code=200, response_time_ms=delay_ms, error=None)


def _overdue() -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=5)


def _make_ctx(**settings_overrides: object) -> _RunnerContext:
    settings = get_settings().model_copy(update=settings_overrides)
    probe = StubProbe(delay_min_ms=10, delay_max_ms=10, outcome="up")
    ctx = _RunnerContext(
        runner_id=f"test-runner-{uuid.uuid4().hex[:8]}",
        settings=settings,
        probe=probe,
        redis=FailOpenRedis(settings.redis_url),
    )
    # Simulates "a canary round already ran" so on_tick's interval gate doesn't spawn an
    # unawaited background canary task in every test that isn't actually testing canaries --
    # see tests/engine/test_canary.py for the dedicated scheduling/degradation tests.
    ctx.last_canary_round_at = time.monotonic()
    return ctx


async def test_capacity_never_exceeds_runner_concurrency(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    monitors = [
        await make_monitor(db_session, account.id, next_check_at=_overdue(), interval_seconds=60)
        for _ in range(12)
    ]
    await db_session.commit()

    ctx = _make_ctx(runner_concurrency=5, runner_pool_size=5, runner_max_overflow=5)
    ctx.probe = StubProbe(delay_min_ms=400, delay_max_ms=400, outcome="up")
    try:
        max_observed = 0
        deadline = asyncio.get_running_loop().time() + 10
        while asyncio.get_running_loop().time() < deadline:
            await on_tick(ctx)
            max_observed = max(max_observed, len(ctx.in_flight_tasks))
            rows_so_far = (
                await db_session.execute(
                    select(CheckResult).where(
                        CheckResult.monitor_id.in_([m.id for m in monitors])
                    )
                )
            ).all()
            if len(rows_so_far) == 12 and not ctx.in_flight_tasks:
                break
            await asyncio.sleep(0.15)
        assert max_observed <= 5
    finally:
        await ctx.engine.dispose()

    rows = (
        await db_session.execute(
            select(CheckResult).where(CheckResult.monitor_id.in_([m.id for m in monitors]))
        )
    ).all()
    assert len(rows) == 12, "every monitor should have been claimed across several ticks"


async def test_no_connection_held_during_probe(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    monitor = await make_monitor(db_session, account.id, next_check_at=_overdue())
    await db_session.commit()
    claimed = await claim_due_monitors(db_session, free_slots=10)
    await db_session.commit()
    assert len(claimed) == 1

    ctx = _make_ctx(runner_pool_size=5, runner_max_overflow=0)
    ctx.probe = StubProbe(delay_min_ms=600, delay_max_ms=600, outcome="up")
    try:
        task = asyncio.create_task(_run_one(ctx, claimed[0]))
        await asyncio.sleep(0.2)
        assert ctx.engine.pool.checkedout() == 0, "a connection is held during the probe"
        await task
        assert ctx.engine.pool.checkedout() == 0
    finally:
        await ctx.engine.dispose()

    row = (
        await db_session.execute(select(CheckResult).where(CheckResult.monitor_id == monitor.id))
    ).scalar_one()
    assert row.is_up is True


async def test_task_deadline_abandons_a_blocked_result_write(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    """The result write blocks on a row lock held by a second session. The per-task deadline
    (monitor.timeout_seconds + runner_task_margin_seconds) must fire before the DB's own
    lock_timeout would -- so runner_claim_lock_timeout_ms here is set deliberately long, to
    prove this is the OUTER asyncio.timeout layer catching it, not the inner DB-level one
    (that path has its own dedicated test in test_claim.py)."""
    account = await make_account(db_session)
    monitor = await make_monitor(
        db_session, account.id, next_check_at=_overdue(), timeout_seconds=1, interval_seconds=30
    )
    await db_session.commit()
    claimed = await claim_due_monitors(db_session, free_slots=10)
    await db_session.commit()
    assert len(claimed) == 1

    ctx = _make_ctx(
        runner_task_margin_seconds=1,
        runner_claim_lock_timeout_ms=30_000,
        runner_claim_statement_timeout_ms=30_000,
    )
    ctx.probe = StubProbe(delay_min_ms=10, delay_max_ms=10, outcome="up")

    locker_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    locker_session = locker_factory()
    # Holds a row lock on the monitor via autobegin -- not released until rollback() below --
    # so write_result's UPDATE on this same row blocks until the deadline cancels the task.
    await locker_session.get(Monitor, monitor.id, with_for_update=True)

    try:
        _spawn(ctx, claimed[0])
        task = next(iter(ctx.in_flight_tasks))
        start = asyncio.get_running_loop().time()
        await task
        elapsed = asyncio.get_running_loop().time() - start
        # deadline is ~2s (timeout_seconds=1 + margin=1); generous headroom for CI jitter.
        assert elapsed < 10
        assert task not in ctx.in_flight_tasks
    finally:
        await locker_session.rollback()
        await locker_session.close()
        await ctx.engine.dispose()

    row = (
        await db_session.execute(select(CheckResult).where(CheckResult.monitor_id == monitor.id))
    ).first()
    assert row is None, "the abandoned write must not have landed"


async def test_db_outage_on_tick_never_raises_and_increments_failures() -> None:
    settings = get_settings().model_copy(
        update={"database_url": "postgresql+asyncpg://nouser:nopass@127.0.0.1:1/does_not_exist"}
    )
    probe = StubProbe(delay_min_ms=10, delay_max_ms=10, outcome="up")
    ctx = _RunnerContext(
        runner_id="test-outage-runner",
        settings=settings,
        probe=probe,
        redis=FailOpenRedis(settings.redis_url),
    )
    ctx.last_canary_round_at = time.monotonic()
    try:
        await on_tick(ctx)  # must not raise
        assert ctx.consecutive_db_failures >= 1
    finally:
        await ctx.engine.dispose()


async def test_db_outage_recovery_resets_failure_counter() -> None:
    ctx = _make_ctx()
    ctx.consecutive_db_failures = 2
    try:
        await on_tick(ctx)  # healthy DB, nothing due -- should succeed cleanly
        assert ctx.consecutive_db_failures == 0
    finally:
        await ctx.engine.dispose()


async def test_shutdown_drain_finishes_fast_tasks_and_abandons_slow_ones(
    db_session: AsyncSession,
) -> None:
    account = await make_account(db_session)
    fast_monitor = await make_monitor(db_session, account.id, next_check_at=_overdue())
    slow_monitor = await make_monitor(db_session, account.id, next_check_at=_overdue())
    await db_session.commit()
    claimed = await claim_due_monitors(db_session, free_slots=10)
    await db_session.commit()
    claimed_by_id = {c.id: c for c in claimed}

    ctx = _make_ctx(runner_drain_seconds=1)
    try:
        ctx.probe = _DelayByMonitor({fast_monitor.id: 50, slow_monitor.id: 5000})
        _spawn(ctx, claimed_by_id[fast_monitor.id])
        _spawn(ctx, claimed_by_id[slow_monitor.id])

        # 3s, not 1s: a freshly created engine's first query pays real connection-setup cost
        # on a loaded host -- still an order of magnitude under the slow task's 5s probe delay.
        done, pending = await asyncio.wait(ctx.in_flight_tasks, timeout=3)
        assert len(done) == 1
        assert len(pending) == 1
    finally:
        await ctx.engine.dispose()

    fast_row = (
        await db_session.execute(
            select(CheckResult).where(CheckResult.monitor_id == fast_monitor.id)
        )
    ).first()
    assert fast_row is not None

    slow_row = (
        await db_session.execute(
            select(CheckResult).where(CheckResult.monitor_id == slow_monitor.id)
        )
    ).first()
    assert slow_row is None


async def test_canary_round_gated_by_interval() -> None:
    ctx = _make_ctx(canary_interval_seconds=30)
    try:
        ctx.last_canary_round_at = time.monotonic()
        _maybe_schedule_canary_round(ctx)
        assert ctx.canary_tasks == set(), "not due yet -- interval hasn't elapsed"

        ctx.last_canary_round_at = time.monotonic() - 31
        _maybe_schedule_canary_round(ctx)
        assert len(ctx.canary_tasks) == 1
        await asyncio.gather(*ctx.canary_tasks)
        assert ctx.canary.ok is True  # StubProbe(outcome="up") -- every canary URL "succeeds"
    finally:
        await ctx.engine.dispose()


def test_build_default_probe_returns_stub_for_stub_kind() -> None:
    settings = get_settings().model_copy(update={"probe_kind": "stub"})
    probe = _build_default_probe(settings)
    assert isinstance(probe, StubProbe)


def test_build_default_probe_returns_http_for_http_kind() -> None:
    settings = get_settings().model_copy(update={"probe_kind": "http"})
    probe = _build_default_probe(settings)
    assert isinstance(probe, HttpProbe)


async def test_runner_skips_write_on_host_cap_exceeded(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    monitor = await make_monitor(
        db_session, account.id, next_check_at=_overdue(), url="https://capped.example/x"
    )
    await db_session.commit()
    claimed = await claim_due_monitors(db_session, free_slots=10)
    await db_session.commit()
    assert len(claimed) == 1

    ctx = _make_ctx(probe_host_cap_per_minute=1)
    ctx.probe = StubProbe(delay_min_ms=10, delay_max_ms=10, outcome="up")
    try:
        # Exhaust the cap for this host before the runner ever gets a chance to probe it.
        await ctx.redis.incr_with_ttl("ratelimit:probe:host:capped.example", window_seconds=60)
        await _run_one(ctx, claimed[0])
    finally:
        await ctx.engine.dispose()

    row = (
        await db_session.execute(select(CheckResult).where(CheckResult.monitor_id == monitor.id))
    ).first()
    assert row is None, "a host over its politeness cap must get no check_results row this cycle"
