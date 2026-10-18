from __future__ import annotations

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@pytest_asyncio.fixture(autouse=True)
async def _clear_claimable_tables(db_engine: AsyncEngine) -> None:
    """claim_due_monitors claims EVERY due+active monitor in the table, not just a test's own --
    a monitor left behind active+due by one test (e.g. test_claim_respects_limit's unclaimed
    overflow) leaks into the next test's claim and inflates its count. Truncating before every
    test in this directory (not just test_claim.py -- test_results.py/test_runner.py claim too)
    guarantees each test starts from an empty slate, the same role _clear_runner_state already
    plays for that one table. Day 8 extends this to notifications/incidents -- state.py now
    writes both from inside the same engine tests this fixture already covers."""
    async with db_engine.connect() as conn:
        await conn.execute(
            text("TRUNCATE TABLE notifications, incidents, check_results, monitors, accounts CASCADE")
        )
        await conn.commit()
