"""Audits a specific hazard with async DBAPI drivers: asyncio.timeout (or any cancellation)
firing while a coroutine is awaiting an in-flight asyncpg call can abandon that call mid-
protocol. If the pool then checks the same physical connection back in as "clean" rather than
discarding it, the next checkout gets a connection asyncpg itself considers busy, surfacing as
InternalClientError("cannot switch to state 11; another operation (2) is in progress") -- seen
once live during Day 6's acceptance test. This proves whether SQLAlchemy's asyncpg dialect
already invalidates on cancellation (it does, as of the asyncio-safe event-loop integration
added for exactly this class of bug) rather than asserting it from memory.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.engine.claim import claim_due_monitors
from app.engine.db_bounds import bounded_transaction
from app.engine.probe import ProbeResult
from app.engine.results import write_result
from tests.helpers import make_account, make_monitor

_UP_RESULT = ProbeResult(is_up=True, status_code=200, response_time_ms=1, error=None)


async def _cancel_mid_pg_sleep(session_factory) -> None:
    """Mimics _run_one's DB section: open a session, begin a bounded transaction, run a slow
    statement -- then get cancelled while it's still in flight, exactly as asyncio.timeout does
    to a real task whose result write is taking too long."""
    settings = get_settings()
    async with session_factory() as session:
        async with bounded_transaction(
            session,
            lock_timeout_ms=settings.runner_claim_lock_timeout_ms,
            statement_timeout_ms=settings.runner_claim_statement_timeout_ms,
        ):
            await session.execute(text("SELECT pg_sleep(5)"))


async def test_repeated_mid_write_cancellation_never_poisons_the_pool(
    db_session: AsyncSession,
) -> None:
    # A small pool (matches the Day 6 follow-up's production sizing intent) forces the 200
    # normal writes below to actually reuse connections that survived the cancellation loop,
    # rather than each getting a pristine one from a large, mostly-idle pool.
    engine = create_engine(get_settings(), pool_size=3, max_overflow=0)
    session_factory = create_session_factory(engine)

    try:
        for _ in range(20):
            task = asyncio.create_task(_cancel_mid_pg_sleep(session_factory))
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        account = await make_account(db_session)
        now = datetime.now(timezone.utc) - timedelta(seconds=5)
        for _ in range(200):
            await make_monitor(db_session, account.id, next_check_at=now)
        await db_session.commit()
        claimed = await claim_due_monitors(db_session, free_slots=200)
        await db_session.commit()
        assert len(claimed) == 200

        errors: list[Exception] = []
        written_count = 0
        for item in claimed:
            try:
                settings = get_settings()
                async with session_factory() as session:
                    async with bounded_transaction(
                        session,
                        lock_timeout_ms=settings.runner_claim_lock_timeout_ms,
                        statement_timeout_ms=settings.runner_claim_statement_timeout_ms,
                    ):
                        written = await write_result(session, item, _UP_RESULT)
                if written:
                    written_count += 1
            except DBAPIError as exc:  # noqa: PERF203 - this is exactly what we're checking for
                errors.append(exc)

        assert errors == [], (
            f"{len(errors)} of 200 writes hit a DBAPIError after the cancellation storm: "
            f"{errors[:3]!r}"
        )
        assert written_count == 200
    finally:
        await engine.dispose()
