"""Shared helper so every runner/notifier transaction runs with lock_timeout and
statement_timeout -- no transaction runs unbounded. A caught timeout is the caller's to log and
treat as "nothing done this attempt", never to let crash the tick loop.

Takes explicit ms values rather than a Settings object: the runner and the notifier each read
their own differently-named Settings fields (runner_claim_*_timeout_ms vs
notifier_claim_*_timeout_ms) into this one shared helper, instead of each process needing its own
near-identical copy of the function body.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@asynccontextmanager
async def bounded_transaction(
    session: AsyncSession, *, lock_timeout_ms: int, statement_timeout_ms: int
) -> AsyncIterator[None]:
    # Postgres's SET/SET LOCAL grammar has no bind-parameter form at all -- a literal is the
    # only option here, unlike every other query in this codebase. Safe because both values are
    # int-typed Settings fields (process config, never request/user input), not interpolated
    # strings from anywhere external; int(...) below is a defensive cast, not a trust boundary.
    lock_timeout_ms = int(lock_timeout_ms)
    statement_timeout_ms = int(statement_timeout_ms)
    async with session.begin():
        await session.execute(text(f"SET LOCAL lock_timeout = '{lock_timeout_ms}ms'"))
        await session.execute(
            text(f"SET LOCAL statement_timeout = '{statement_timeout_ms}ms'")
        )
        yield
