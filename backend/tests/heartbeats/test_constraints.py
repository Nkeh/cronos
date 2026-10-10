from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.heartbeats.models import Heartbeat, HeartbeatPing
from tests.helpers import make_account, make_heartbeat, make_heartbeat_ping, make_heartbeat_slug


@pytest.mark.parametrize(
    "overrides",
    [
        {"slug": "too-short"},
        {"period_seconds": 10},
        {"grace_seconds": -1},
        {"status": "deleted"},
        {"last_ping_kind": "maybe"},
    ],
    ids=["slug_format", "period_floor", "grace_nonneg", "status", "last_ping_kind"],
)
async def test_heartbeat_check_violations(db_session: AsyncSession, overrides: dict) -> None:
    account = await make_account(db_session)
    with pytest.raises(IntegrityError):
        await make_heartbeat(db_session, account.id, **overrides)
    await db_session.rollback()


async def test_heartbeat_slug_unique(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    slug = make_heartbeat_slug()
    await make_heartbeat(db_session, account.id, slug=slug)
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await make_heartbeat(db_session, account.id, slug=slug)
    await db_session.rollback()


async def test_heartbeat_paused_matches_active_invariant_both_directions(
    db_session: AsyncSession,
) -> None:
    account = await make_account(db_session)
    account_id = account.id
    # Commit before the violating attempts — each rollback() below undoes
    # the *whole* transaction (which would otherwise also undo this account
    # insert, since make_account only flushes) and expires every object in
    # the identity map, so account_id is captured up front and reused.
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await make_heartbeat(db_session, account_id, status="paused", is_active=True)
    await db_session.rollback()

    with pytest.raises(IntegrityError):
        await make_heartbeat(db_session, account_id, status="new", is_active=False)
    await db_session.rollback()

    await make_heartbeat(db_session, account_id, status="paused", is_active=False)
    await make_heartbeat(db_session, account_id, status="new", is_active=True)


async def test_heartbeat_ping_kind_check(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    heartbeat = await make_heartbeat(db_session, account.id)
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await make_heartbeat_ping(db_session, heartbeat.id, kind="maybe")
    await db_session.rollback()


async def test_heartbeat_ping_user_agent_length(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    heartbeat = await make_heartbeat(db_session, account.id)
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await make_heartbeat_ping(db_session, heartbeat.id, user_agent="x" * 257)
    await db_session.rollback()


async def test_deleting_heartbeat_cascades_pings(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    heartbeat = await make_heartbeat(db_session, account.id)
    ping = await make_heartbeat_ping(db_session, heartbeat.id)
    heartbeat_id, ping_id = heartbeat.id, ping.id
    await db_session.commit()

    await db_session.delete(await db_session.get(Heartbeat, heartbeat_id))
    await db_session.commit()
    db_session.expire_all()

    assert await db_session.get(HeartbeatPing, ping_id) is None
