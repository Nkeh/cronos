from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import RunnerState
from app.engine.runner_state import delete_runner_state, upsert_runner_state


async def test_upsert_runner_state_creates_row(db_session: AsyncSession) -> None:
    runner_id = f"runner-{uuid.uuid4().hex[:8]}"
    await upsert_runner_state(db_session, runner_id, in_flight=3, lag_seconds=1.5)
    await db_session.commit()

    row = await db_session.get(RunnerState, runner_id)
    assert row is not None
    assert row.in_flight == 3
    assert row.lag_seconds == 1.5
    assert row.last_tick_at is not None


async def test_upsert_runner_state_is_idempotent(db_session: AsyncSession) -> None:
    runner_id = f"runner-{uuid.uuid4().hex[:8]}"
    await upsert_runner_state(db_session, runner_id, in_flight=1, lag_seconds=0.0)
    await db_session.commit()
    first = await db_session.get(RunnerState, runner_id)
    first_tick = first.last_tick_at

    await upsert_runner_state(db_session, runner_id, in_flight=9, lag_seconds=4.2)
    await db_session.commit()
    # upsert_runner_state is raw SQL (on_conflict_do_update) -- bypasses the ORM unit-of-work,
    # so `first` (already in this session's identity map) would otherwise mask the update.
    db_session.expire_all()

    rows = (
        await db_session.execute(select(RunnerState).where(RunnerState.runner_id == runner_id))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].in_flight == 9
    assert rows[0].lag_seconds == 4.2
    assert rows[0].last_tick_at >= first_tick


async def test_delete_runner_state_removes_row(db_session: AsyncSession) -> None:
    runner_id = f"runner-{uuid.uuid4().hex[:8]}"
    await upsert_runner_state(db_session, runner_id, in_flight=0, lag_seconds=0.0)
    await db_session.commit()

    await delete_runner_state(db_session, runner_id)
    await db_session.commit()

    assert await db_session.get(RunnerState, runner_id) is None


async def test_delete_runner_state_on_nonexistent_id_is_a_no_op(db_session: AsyncSession) -> None:
    await delete_runner_state(db_session, f"runner-{uuid.uuid4().hex[:8]}")
    await db_session.commit()
