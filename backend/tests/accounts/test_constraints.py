from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import Account, UsageEvent
from app.auth.models import User
from tests.helpers import make_account, make_user


async def test_account_plan_defaults_to_launch(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    assert account.plan == "launch"


async def test_account_plan_check_rejects_other_values(db_session: AsyncSession) -> None:
    db_session.add(Account(plan="pro"))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_usage_event_quantity_nonneg(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    db_session.add(
        UsageEvent(account_id=account.id, day=date(2026, 1, 1), kind="checks", quantity=-1)
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_usage_event_valid_row_succeeds(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    db_session.add(
        UsageEvent(account_id=account.id, day=date(2026, 1, 1), kind="checks", quantity=5)
    )
    await db_session.flush()


async def test_deleting_account_cascades_users(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    user = await make_user(db_session, account.id)
    account_id, user_id = account.id, user.id
    await db_session.commit()

    await db_session.delete(await db_session.get(Account, account_id))
    await db_session.commit()
    # expire_on_commit=False means `user` would otherwise still look live in
    # the identity map — force a real read so the DB-level cascade shows up.
    db_session.expire_all()

    assert await db_session.get(User, user_id) is None
