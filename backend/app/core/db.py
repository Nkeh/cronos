"""Async engine/session plumbing. Postgres is the clock, the queue and the source of truth."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import structlog
from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings

logger = structlog.get_logger()


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"server_settings": {"timezone": "UTC"}},
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Per-request session dependency.

    Rolls back on any exception and always closes, but does NOT auto-commit
    on a clean return — that would make the transaction boundary an inferred
    side effect of FastAPI's dependency-teardown timing relative to
    BackgroundTasks, rather than a fact visible in each route's own code.
    Routes that write call `await session.commit()` themselves, explicitly,
    before scheduling any BackgroundTask and before returning.
    """
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def wait_for_database(dsn: str, *, retries: int = 30, delay_seconds: float = 1.0) -> None:
    """Retries with backoff until Postgres answers `SELECT 1`, or gives up.

    Used by the runner and notifier at startup: there's nothing useful for
    either to do until Postgres is reachable.
    """
    engine = create_async_engine(dsn)
    try:
        for attempt in range(1, retries + 1):
            try:
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
                logger.info("database_ready", attempt=attempt)
                return
            except Exception as exc:  # noqa: BLE001 - any connect failure should retry
                logger.warning("database_not_ready", attempt=attempt, error=str(exc))
                await asyncio.sleep(delay_seconds)
        raise RuntimeError("database did not become ready in time")
    finally:
        await engine.dispose()
