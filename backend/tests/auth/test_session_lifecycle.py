from __future__ import annotations

from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Session, User
from app.core.clock import SystemClock
from tests.helpers import make_account, make_user, make_valid_session


async def _make_session_for_me(
    db_session: AsyncSession, clock: SystemClock, **overrides
) -> tuple[User, str, Session]:
    account = await make_account(db_session)
    user = await make_user(db_session, account.id)
    raw_token, row = await make_valid_session(db_session, user.id, clock, **overrides)
    await db_session.commit()
    return user, raw_token, row


async def test_me_valid_session(client: AsyncClient, db_session: AsyncSession) -> None:
    clock = SystemClock()
    user, raw_token, _ = await _make_session_for_me(db_session, clock)
    client.cookies.set("cronos_session", raw_token)

    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["user_id"] == str(user.id)


async def test_me_absolute_expired_session_rejected(client: AsyncClient, db_session: AsyncSession) -> None:
    clock = SystemClock()
    _, raw_token, _ = await _make_session_for_me(
        db_session, clock, expires_at=clock.now() - timedelta(days=1)
    )
    client.cookies.set("cronos_session", raw_token)

    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_me_idle_expired_session_rejected(client: AsyncClient, db_session: AsyncSession) -> None:
    """Idle timeout is checked against last_seen_at, not expires_at — a
    session set up directly in the DB with a stale last_seen_at, exactly as
    the plan specifies (no Python clock involved in the comparison)."""
    clock = SystemClock()
    _, raw_token, row = await _make_session_for_me(db_session, clock)
    await db_session.execute(
        text("UPDATE sessions SET last_seen_at = now() - interval '8 days' WHERE id = :id"),
        {"id": row.id},
    )
    await db_session.commit()
    client.cookies.set("cronos_session", raw_token)

    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_last_seen_bump_is_rate_limited_to_five_minutes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    clock = SystemClock()
    _, raw_token, row = await _make_session_for_me(db_session, clock)
    client.cookies.set("cronos_session", raw_token)

    async def read_last_seen():
        return (
            await db_session.execute(
                text("SELECT last_seen_at FROM sessions WHERE id = :id"), {"id": row.id}
            )
        ).scalar_one()

    before = await read_last_seen()

    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert await read_last_seen() == before  # just created — too soon to bump again

    await db_session.execute(
        text("UPDATE sessions SET last_seen_at = now() - interval '6 minutes' WHERE id = :id"),
        {"id": row.id},
    )
    await db_session.commit()

    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert await read_last_seen() > before
