from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import ApiKey, AuthToken, Session, User
from tests.helpers import make_account, make_api_key, make_auth_token, make_session, make_user


async def test_user_email_unique_case_insensitive(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    local_part = uuid.uuid4().hex
    await make_user(db_session, account.id, email=f"Dup_{local_part}@Example.com")
    await db_session.commit()

    db_session.add(
        User(
            account_id=account.id,
            email=f"dup_{local_part}@example.com",
            password_hash="x",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_session_id_format_rejects_non_hex(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    user = await make_user(db_session, account.id)
    await db_session.commit()

    db_session.add(
        Session(id="not-a-sha256-hash", user_id=user.id, expires_at=datetime.now(timezone.utc))
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_deleting_user_cascades_sessions(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    user = await make_user(db_session, account.id)
    session_row = await make_session(db_session, user.id)
    user_id, session_id = user.id, session_row.id
    await db_session.commit()

    await db_session.delete(await db_session.get(User, user_id))
    await db_session.commit()
    db_session.expire_all()

    assert await db_session.get(Session, session_id) is None


async def test_api_key_prefix_unique(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    prefix = f"ck_dup_{uuid.uuid4().hex[:12]}"
    await make_api_key(db_session, account.id, prefix=prefix)
    await db_session.commit()

    db_session.add(ApiKey(account_id=account.id, prefix=prefix, key_hash="x"))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_auth_token_purpose_check(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    user = await make_user(db_session, account.id)
    await db_session.commit()

    db_session.add(
        AuthToken(
            user_id=user.id,
            purpose="not_a_real_purpose",
            token_hash="x",
            expires_at=datetime.now(timezone.utc),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_auth_token_valid_purpose_succeeds(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    user = await make_user(db_session, account.id)
    await db_session.commit()

    await make_auth_token(db_session, user.id, purpose="reset_password")
