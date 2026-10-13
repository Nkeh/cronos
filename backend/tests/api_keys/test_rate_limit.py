from __future__ import annotations

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_keys import generate_api_key
from app.core.clock import SystemClock
from app.core.config import get_settings
from app.core.email import FakeEmailSender
from app.main import create_app
from tests.helpers import make_account, make_api_key, make_user


@pytest_asyncio.fixture
async def low_limit_app():
    settings = get_settings().model_copy(update={"rate_limit_api_key_max": 3})
    application = create_app(settings=settings, clock=SystemClock(), email_sender=FakeEmailSender())
    async with application.router.lifespan_context(application):
        yield application


async def test_per_key_limit_is_enforced_in_authenticate_not_per_router(
    low_limit_app: FastAPI, db_session: AsyncSession
) -> None:
    """Hits the limit on one router (/monitors), then confirms the SAME key
    is already 429 on a completely different router (/usage) — proving the
    limit lives inside authenticate() itself, not attached per-router."""
    settings = low_limit_app.state.settings
    account = await make_account(db_session)
    user = await make_user(db_session, account.id)
    full_key, prefix, key_hash = generate_api_key()
    await make_api_key(
        db_session,
        account.id,
        prefix=prefix,
        key_hash=key_hash,
        scopes=["monitors:read"],
        created_by_user_id=user.id,
    )
    await db_session.commit()

    headers = {"Authorization": f"Bearer {full_key}"}
    async with AsyncClient(
        transport=ASGITransport(app=low_limit_app), base_url="http://testserver"
    ) as client:
        for _ in range(settings.rate_limit_api_key_max):
            resp = await client.get("/api/v1/monitors", headers=headers)
            assert resp.status_code == 200

        limited = await client.get("/api/v1/monitors", headers=headers)
        assert limited.status_code == 429
        assert "Retry-After" in limited.headers

        also_limited = await client.get("/api/v1/usage", headers=headers)
        assert also_limited.status_code == 429
