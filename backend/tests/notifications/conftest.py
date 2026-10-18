from __future__ import annotations

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@pytest_asyncio.fixture(autouse=True)
async def _clear_notifications(db_engine: AsyncEngine) -> None:
    """Several tests here assert the notifications table is globally empty (zero rows, no
    per-test filter) -- a prior test's committed row (e.g. a successful enqueue_notifications
    fan-out) leaks into that assertion otherwise. Mirrors tests/engine/conftest.py's
    _clear_claimable_tables, scoped to just the one table this directory's tests care about."""
    async with db_engine.connect() as conn:
        await conn.execute(text("TRUNCATE TABLE notifications CASCADE"))
        await conn.commit()
