from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import create_app


async def test_healthz_returns_ok_with_no_io(client: AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_reports_db_ok(client: AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["db"] == "ok"


async def test_readyz_reports_redis_unavailable_but_still_returns_200() -> None:
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
