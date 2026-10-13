"""Proves get_account_for_update actually takes a row lock, not just that
the plan-limit count is correct — a passing count-based test (test_plan_limits
.py) can't distinguish "the lock worked" from "the race never actually
collided." This goes straight at the lock itself: hold it open in one
session (no commit yet), then try `SELECT ... FOR UPDATE NOWAIT` on the same
row from an independent second connection and confirm it fails immediately
rather than blocking or succeeding.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.accounts.models import Account
from app.plans.dependencies import get_account_for_update
from tests.helpers import make_account


async def _assert_second_connection_cannot_lock(db_engine: AsyncEngine, account_id) -> None:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as other_session:
        with pytest.raises(DBAPIError, match="(?i)lock"):
            await other_session.execute(
                text("SELECT id FROM accounts WHERE id = :id FOR UPDATE NOWAIT"),
                {"id": account_id},
            )
        await other_session.rollback()


async def test_lock_is_actually_held_against_a_second_connection(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    account = await make_account(db_session)
    await db_session.commit()

    # Holds the lock open — deliberately no commit/rollback until the end.
    locked = await get_account_for_update(db_session, account.id)
    assert locked.id == account.id

    await _assert_second_connection_cannot_lock(db_engine, account.id)

    await db_session.rollback()  # release the lock


async def test_lock_is_held_even_when_the_account_was_already_loaded_first(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    """The exact shape of the bug this guards against: a plain db.get()
    earlier in the same session populates the identity map; without
    populate_existing=True, the later with_for_update=True call would have
    returned the cached object and silently never issued the locking SELECT."""
    account = await make_account(db_session)
    await db_session.commit()

    preloaded = await db_session.get(Account, account.id)
    assert preloaded is not None

    locked = await get_account_for_update(db_session, account.id)
    assert locked.id == account.id
    assert locked is preloaded  # same identity-mapped object, but really re-locked

    await _assert_second_connection_cannot_lock(db_engine, account.id)

    await db_session.rollback()
