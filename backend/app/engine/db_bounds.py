"""Shared helper so every runner transaction runs with lock_timeout and statement_timeout --
no transaction runs unbounded. A caught timeout is the caller's to log and treat as "nothing
done this attempt", never to let crash the tick loop.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings


@asynccontextmanager
async def bounded_transaction(session: AsyncSession, settings: Settings) -> AsyncIterator[None]:
    # Postgres's SET/SET LOCAL grammar has no bind-parameter form at all -- a literal is the
    # only option here, unlike every other query in this codebase. Safe because both values are
    # int-typed Settings fields (process config, never request/user input), not interpolated
    # strings from anywhere external; int(...) below is a defensive cast, not a trust boundary.
    lock_timeout_ms = int(settings.runner_claim_lock_timeout_ms)
    statement_timeout_ms = int(settings.runner_claim_statement_timeout_ms)
    async with session.begin():
        await session.execute(text(f"SET LOCAL lock_timeout = '{lock_timeout_ms}ms'"))
        await session.execute(
            text(f"SET LOCAL statement_timeout = '{statement_timeout_ms}ms'")
        )
        yield
