from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.engine.runner_state import upsert_runner_state
from app.main import create_app


async def test_healthz_returns_ok_with_no_io(client: AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_reports_db_ok(client: AsyncClient, db_session: AsyncSession) -> None:
    # A fresh runner_state row (Day 6) is required for "ok" -- see test_readyz_runner_stale_*
    # below for the no-row/stale-row cases this endpoint also covers.
    await upsert_runner_state(db_session, f"runner-{uuid.uuid4().hex[:8]}", 0, 0.0)
    await db_session.commit()

    response = await client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["db"] == "ok"
    assert body["checks"]["runner"] == "ok"
    assert body["checks"]["canary"] == "ok"  # canary_ok defaults True


async def test_readyz_reports_canary_degraded_but_still_returns_200(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await upsert_runner_state(
        db_session, f"runner-{uuid.uuid4().hex[:8]}", 0, 0.0, canary_ok=False
    )
    await db_session.commit()

    response = await client.get("/readyz")
    # Canary health is advisory -- never fails readiness on its own.
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["runner"] == "ok"
    assert body["checks"]["canary"] == "degraded"


async def test_readyz_reports_redis_unavailable_but_still_returns_200(
    db_session: AsyncSession,
) -> None:
    await upsert_runner_state(db_session, f"runner-{uuid.uuid4().hex[:8]}", 0, 0.0)
    await db_session.commit()

    settings = get_settings().model_copy(
        update={"redis_url": "redis://redis-does-not-exist.invalid:6399/0"}
    )
    app = create_app(settings=settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as c:
            response = await c.get("/readyz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["redis"] == "unavailable"
    assert body["checks"]["db"] == "ok"
    assert body["checks"]["runner"] == "ok"


async def test_readyz_reports_runner_stale_when_no_runner_state_row(
    client: AsyncClient,
) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["runner"] == "stale"


async def test_readyz_reports_runner_stale_when_last_tick_too_old(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    stale_at = datetime.now(timezone.utc) - timedelta(seconds=45)
    await db_session.execute(
        text(
            "INSERT INTO runner_state (runner_id, last_tick_at, in_flight, lag_seconds) "
            "VALUES (:runner_id, :last_tick_at, 0, 0)"
        ),
        {"runner_id": f"runner-{uuid.uuid4().hex[:8]}", "last_tick_at": stale_at},
    )
    await db_session.commit()

    response = await client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["runner"] == "stale"
