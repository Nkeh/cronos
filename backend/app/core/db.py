"""Async engine/session plumbing. Postgres is the clock, the queue and the source of truth."""

from __future__ import annotations

import asyncio

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings

logger = structlog.get_logger()


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


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
