from __future__ import annotations

import os
import subprocess
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from urllib.parse import urlsplit

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.clock import FrozenClock, SystemClock
from app.core.config import get_settings
from app.core.db import create_engine
from app.core.email import FakeEmailSender
from app.main import create_app


@pytest.fixture(scope="session", autouse=True)
def _point_at_test_database() -> None:
    """Every test in this session talks to cronos_test, migrated for real.

    DATABASE_URL is repointed at DATABASE_URL_TEST for the whole process, then
    `alembic upgrade head` runs against it — tests exercise the real migration
    path, never `metadata.create_all`.
    """
    test_url = os.environ["DATABASE_URL_TEST"]
    os.environ["DATABASE_URL"] = test_url
    get_settings.cache_clear()

    subprocess.run(
        ["alembic", "upgrade", "head"],
        check=True,
        cwd="/app",
        env={**os.environ, "DATABASE_URL": test_url},
    )


@pytest.fixture(scope="session", autouse=True)
def _point_at_test_redis() -> None:
    """Every test talks to a dedicated, non-zero Redis database (REDIS_URL_TEST,
    e.g. .../15), never db 0 — db 0 is the real dev database, and the autouse
    _flush_redis fixture below would otherwise wipe live dev state out from
    under anyone using the dev stack alongside the test suite. Same repointing
    pattern as _point_at_test_database.
    """
    os.environ["REDIS_URL"] = os.environ["REDIS_URL_TEST"]
    get_settings.cache_clear()


def _redis_db_index(url: str) -> str:
    return urlsplit(url).path.lstrip("/") or "0"


@pytest_asyncio.fixture(autouse=True)
async def _flush_redis() -> None:
    """Redis holds rate-limit counters keyed by (hashed) email/IP — unlike
    Postgres rows, which get fresh randomized data per test, these keys are
    small and finite (one per IP/email actually used), so without a flush
    they'd accumulate across every test in the whole session and eventually
    trip unrelated tests' rate limits. Redis is explicitly non-critical/
    disposable (fail-open, rate limits and caches only), so flushing it
    before every test is always safe — PROVIDED it's actually the dedicated
    test database. This refuses to run at all otherwise: flushing db 0 would
    silently destroy real dev state, and that failure mode must be loud, not
    a quietly wrong default.
    """
    from redis.asyncio import Redis

    settings = get_settings()
    active_db = _redis_db_index(settings.redis_url)
    expected_db = _redis_db_index(os.environ["REDIS_URL_TEST"])

    if active_db == "0" or active_db != expected_db:
        raise RuntimeError(
            f"Refusing to flush Redis: active REDIS_URL points at db {active_db!r}, "
            f"expected the dedicated test db {expected_db!r} (REDIS_URL_TEST), and "
            "never db 0. _point_at_test_redis should have repointed this already — "
            "check REDIS_URL_TEST is set and non-zero."
        )

    redis = Redis.from_url(settings.redis_url)
    try:
        await redis.flushdb()
    finally:
        await redis.aclose()


@pytest_asyncio.fixture
async def app() -> AsyncIterator[FastAPI]:
    """A fresh app per test, with a real (non-frozen) clock and a capturing
    fake email sender instead of real SMTP. SystemClock, not frozen_clock:
    every expiry/idle comparison runs in SQL against Postgres's real now()
    (see core/clock.py wiring), so a frozen-in-the-past clock would make a
    freshly created session/token look expired before the test even runs.
    Tests that need an expired row set expires_at/last_seen_at directly.
    """
    application = create_app(clock=SystemClock(), email_sender=FakeEmailSender())
    async with application.router.lifespan_context(application):
        yield application


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


@pytest.fixture
def frozen_clock() -> FrozenClock:
    return FrozenClock(at=datetime(2026, 1, 1, tzinfo=timezone.utc))


@pytest.fixture(scope="session")
def db_engine() -> AsyncEngine:
    """The same UTC-pinned engine construction the app itself uses.

    Session-scoped to match asyncio_default_fixture_loop_scope="session" —
    a per-test engine would mean a new asyncpg connection pool per test,
    which is the exact class of loop-mismatch bug Day 1 already hit once.
    """
    return create_engine(get_settings())


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        db_engine, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session
