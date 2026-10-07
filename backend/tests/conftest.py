from __future__ import annotations

import os
import subprocess
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.clock import FrozenClock
from app.core.config import get_settings
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


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            yield c


@pytest.fixture
def frozen_clock() -> FrozenClock:
    return FrozenClock(at=datetime(2026, 1, 1, tzinfo=timezone.utc))
