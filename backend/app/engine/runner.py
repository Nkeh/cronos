"""`python -m app.engine.runner` -- ticks every 2s, claims due monitors, probes them, writes
results. See docs/cronos-srs.md Section 7 and docs/progress/day-06.md for the design.
"""

from __future__ import annotations

import asyncio
import pathlib
import socket
from urllib.parse import urlsplit

import structlog
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_session_factory, wait_for_database
from app.core.logging import configure_logging
from app.core.redis import FailOpenRedis
from app.core.tick_loop import run_tick_loop
from app.engine.claim import ClaimedMonitor, claim_due_monitors, oldest_due_lag_seconds
from app.engine.db_bounds import bounded_transaction
from app.engine.host_cap import check_host_cap
from app.engine.http_probe import HttpProbe
from app.engine.probe import Probe, ProbeResult, StubProbe
from app.engine.results import write_result
from app.engine.runner_state import delete_runner_state, upsert_runner_state

TICK_SECONDS = 2
LOG_EVERY_N_TICKS = 30
ALIVE_FILE = pathlib.Path("/tmp/alive")

# Both asyncpg connection failures (DB down, network blip) and a canceled statement/lock wait
# (our own lock_timeout/statement_timeout firing) surface as DBAPIError or a subclass (e.g.
# OperationalError) once a connection exists. But a failure to even ESTABLISH a connection (DB
# host down, DNS failure) happens before any DBAPI-level wrapping -- SQLAlchemy's asyncpg
# dialect re-raises those as plain OSError (ConnectionRefusedError, socket.gaierror, etc.),
# never DBAPIError. Both cases are treated identically: log, lose the slot/claim for this
# attempt, never crash the tick.
_DB_UNAVAILABLE_ERRORS = (DBAPIError, OSError)
# Claim/runner_state treat a pool-checkout timeout the same as any other DB-unavailable
# failure (log, back off, retry next tick); _run_one logs it under its own distinct event name
# instead (see its separate except clauses below).
_RUNNER_TXN_ERRORS = (DBAPIError, OSError, PoolTimeoutError)

logger = structlog.get_logger()


class _RunnerContext:
    """Mutable state shared across ticks and spawned per-monitor tasks. A plain object (not a
    dataclass) because every field below is mutated in place from on_tick/_run_one closures."""

    def __init__(
        self, *, runner_id: str, settings: Settings, probe: Probe, redis: FailOpenRedis
    ) -> None:
        self.runner_id = runner_id
        self.settings = settings
        self.probe = probe
        self.redis = redis
        self.engine = create_engine(
            settings,
            pool_size=settings.runner_pool_size,
            max_overflow=settings.runner_max_overflow,
            pool_timeout=settings.runner_pool_timeout_seconds,
        )
        self.session_factory = create_session_factory(self.engine)
        self.semaphore = asyncio.Semaphore(settings.runner_concurrency)
        self.in_flight_tasks: set[asyncio.Task[None]] = set()
        self.consecutive_db_failures = 0


async def _run_one(ctx: _RunnerContext, claimed: ClaimedMonitor) -> None:
    host = urlsplit(claimed.url).hostname or claimed.url
    within_cap = await check_host_cap(
        ctx.redis, host, limit_per_minute=ctx.settings.probe_host_cap_per_minute
    )
    if not within_cap:
        logger.info(
            "host_cap_skipped",
            monitor_id=str(claimed.id),
            host=host,
            limit_per_minute=ctx.settings.probe_host_cap_per_minute,
        )
        return

    deadline_seconds = claimed.timeout_seconds + ctx.settings.runner_task_margin_seconds
    try:
        async with asyncio.timeout(deadline_seconds):
            async with ctx.semaphore:
                result: ProbeResult = await ctx.probe.check(claimed)
            async with ctx.session_factory() as session:
                async with bounded_transaction(session, ctx.settings):
                    written = await write_result(session, claimed, result)
            if not written:
                logger.info("check_result_discarded_monitor_inactive", monitor_id=str(claimed.id))
    except TimeoutError:
        logger.warning(
            "check_task_abandoned_deadline",
            monitor_id=str(claimed.id),
            deadline_seconds=deadline_seconds,
        )
    except PoolTimeoutError:
        logger.warning("check_result_write_pool_timeout", monitor_id=str(claimed.id))
    except _DB_UNAVAILABLE_ERRORS as exc:
        logger.warning(
            "check_result_write_db_unavailable", monitor_id=str(claimed.id), error=str(exc)
        )
    except Exception:  # noqa: BLE001 - never let one monitor's task crash the runner
        logger.exception("check_task_unexpected_error", monitor_id=str(claimed.id))


def _spawn(ctx: _RunnerContext, claimed: ClaimedMonitor) -> None:
    task = asyncio.create_task(_run_one(ctx, claimed))
    ctx.in_flight_tasks.add(task)
    task.add_done_callback(ctx.in_flight_tasks.discard)


async def _claim_tick(ctx: _RunnerContext) -> list[ClaimedMonitor]:
    free_slots = ctx.settings.runner_concurrency - len(ctx.in_flight_tasks)
    try:
        async with ctx.session_factory() as session:
            async with bounded_transaction(session, ctx.settings):
                return await claim_due_monitors(session, free_slots)
    except _RUNNER_TXN_ERRORS as exc:
        logger.warning("claim_failed", error=str(exc))
        ctx.consecutive_db_failures += 1
        return []


async def _report_runner_state(ctx: _RunnerContext) -> bool:
    """Returns True on success. Runs regardless of the claim's own outcome -- liveness
    reporting must not go stale just because a claim attempt hit a timeout or a DB blip."""
    try:
        async with ctx.session_factory() as session:
            async with bounded_transaction(session, ctx.settings):
                lag_seconds = await oldest_due_lag_seconds(session)
                await upsert_runner_state(
                    session, ctx.runner_id, len(ctx.in_flight_tasks), lag_seconds
                )
        return True
    except _RUNNER_TXN_ERRORS as exc:
        logger.warning("runner_state_upsert_failed", error=str(exc))
        ctx.consecutive_db_failures += 1
        return False


async def on_tick(ctx: _RunnerContext) -> None:
    failures_before = ctx.consecutive_db_failures

    claimed = await _claim_tick(ctx)
    for monitor in claimed:
        _spawn(ctx, monitor)

    state_ok = await _report_runner_state(ctx)

    if ctx.consecutive_db_failures > failures_before:
        # At least one of the two steps above failed this tick -- back off on top of the
        # regular tick interval, capped, before the loop tries again.
        backoff_seconds = min(2**ctx.consecutive_db_failures, 10)
        logger.warning(
            "runner_db_backoff",
            consecutive_failures=ctx.consecutive_db_failures,
            backoff_seconds=backoff_seconds,
        )
        await asyncio.sleep(backoff_seconds)
    elif state_ok:
        ctx.consecutive_db_failures = 0


def _build_default_probe(settings: Settings) -> Probe:
    """Extracted from run() so PROBE_KIND dispatch is unit-testable without spinning up the
    tick loop. An explicit `probe=` kwarg to run() always wins over this, regardless of
    PROBE_KIND."""
    if settings.probe_kind == "stub":
        return StubProbe(
            delay_min_ms=settings.stub_probe_delay_min_ms,
            delay_max_ms=settings.stub_probe_delay_max_ms,
            outcome=settings.stub_probe_outcome,
        )
    return HttpProbe(
        user_agent=f"Cronos/1.0 (+{settings.public_origin}/bot)",
        max_redirects=settings.probe_max_redirects,
        body_cap_bytes=settings.probe_body_cap_bytes,
        allow_hosts=settings.ssrf_allow_hosts_set,
    )


async def run(*, settings: Settings | None = None, probe: Probe | None = None) -> None:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    settings.check_production_guard()

    await wait_for_database(settings.database_url)

    runner_id = socket.gethostname()
    resolved_probe = probe or _build_default_probe(settings)
    redis = FailOpenRedis(settings.redis_url)
    ctx = _RunnerContext(runner_id=runner_id, settings=settings, probe=resolved_probe, redis=redis)

    async def _on_tick(_tick: int) -> None:
        await on_tick(ctx)

    try:
        await run_tick_loop(
            name="runner",
            interval_seconds=TICK_SECONDS,
            log_every=LOG_EVERY_N_TICKS,
            alive_file=ALIVE_FILE,
            on_tick=_on_tick,
        )
    finally:
        if ctx.in_flight_tasks:
            done, pending = await asyncio.wait(
                ctx.in_flight_tasks, timeout=settings.runner_drain_seconds
            )
            logger.info("runner_drain_complete", finished=len(done), abandoned=len(pending))
        else:
            logger.info("runner_drain_complete", finished=0, abandoned=0)

        try:
            async with ctx.session_factory() as session:
                async with bounded_transaction(session, settings):
                    await delete_runner_state(session, runner_id)
        except _RUNNER_TXN_ERRORS as exc:
            logger.warning("runner_state_delete_failed", error=str(exc))

        await ctx.engine.dispose()
        await ctx.redis.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
