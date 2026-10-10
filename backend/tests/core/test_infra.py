from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import ApiAlive, RunnerState, SystemState
from tests.helpers import make_account


async def test_timezone_is_utc(db_session: AsyncSession) -> None:
    result = await db_session.execute(text("SHOW timezone"))
    assert result.scalar() == "UTC"


async def test_updated_at_trigger_fires_on_raw_sql(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    await db_session.commit()

    before = account.updated_at

    # A raw SQL UPDATE, not the ORM — this only changes updated_at if the
    # trigger did it, since no ORM onupdate= is involved at all here.
    await db_session.execute(
        text("UPDATE accounts SET plan = plan WHERE id = :id"), {"id": str(account.id)}
    )
    await db_session.commit()

    result = await db_session.execute(
        text("SELECT updated_at FROM accounts WHERE id = :id"), {"id": str(account.id)}
    )
    after = result.scalar()
    assert after > before


async def test_runner_state_nonneg_checks(db_session: AsyncSession) -> None:
    db_session.add(
        RunnerState(
            runner_id="runner-1", last_tick_at=datetime.now(timezone.utc), in_flight=-1
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_api_alive_and_system_state_roundtrip(db_session: AsyncSession) -> None:
    db_session.add(ApiAlive(instance_id="api-1", last_alive_at=datetime.now(timezone.utc)))
    db_session.add(SystemState(key="ingest_recovered_at", value=datetime.now(timezone.utc)))
    await db_session.flush()
