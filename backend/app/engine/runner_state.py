"""Liveness reporting: upsert/delete this runner's row in runner_state.

Table already exists (migration 0006). last_tick_at is always the DB's now(), never a Python
timestamp -- Postgres is the clock.
"""

from __future__ import annotations

from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import RunnerState


async def upsert_runner_state(
    session: AsyncSession, runner_id: str, in_flight: int, lag_seconds: float
) -> None:
    stmt = (
        pg_insert(RunnerState)
        .values(
            runner_id=runner_id,
            last_tick_at=func.now(),
            in_flight=in_flight,
            lag_seconds=lag_seconds,
        )
        .on_conflict_do_update(
            index_elements=["runner_id"],
            set_={
                "last_tick_at": func.now(),
                "in_flight": in_flight,
                "lag_seconds": lag_seconds,
            },
        )
    )
    await session.execute(stmt)


async def delete_runner_state(session: AsyncSession, runner_id: str) -> None:
    await session.execute(delete(RunnerState).where(RunnerState.runner_id == runner_id))
