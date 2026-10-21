from __future__ import annotations

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@pytest_asyncio.fixture(autouse=True)
async def _clear_notifications(db_engine: AsyncEngine) -> None:
    """Mirrors tests/notifications/conftest.py -- several tests here assert against the global
    notifications/notification_attempts row count, which a prior test's committed rows would
    otherwise pollute."""
    async with db_engine.connect() as conn:
        await conn.execute(text("TRUNCATE TABLE notifications CASCADE"))
        await conn.commit()
