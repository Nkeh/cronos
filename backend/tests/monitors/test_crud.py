from __future__ import annotations

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers import login_as

_PAYLOAD = {"name": "api", "url": "http://chaos:8000/health"}


async def test_create_list_get(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)

    create_resp = await client.post("/api/v1/monitors", json=_PAYLOAD, headers=csrf_headers)
    assert create_resp.status_code == 201
    body = create_resp.json()
    assert body["status"] == "new"
    assert body["is_active"] is True
    assert body["url"] == "http://chaos:8000/health"
    assert body["method"] == "GET"
    assert body["interval_seconds"] == 300
    monitor_id = body["id"]

    list_resp = await client.get("/api/v1/monitors")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    get_resp = await client.get(f"/api/v1/monitors/{monitor_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == monitor_id


async def test_delete(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)
    create_resp = await client.post("/api/v1/monitors", json=_PAYLOAD, headers=csrf_headers)
    monitor_id = create_resp.json()["id"]

    delete_resp = await client.delete(f"/api/v1/monitors/{monitor_id}", headers=csrf_headers)
    assert delete_resp.status_code == 204

    get_resp = await client.get(f"/api/v1/monitors/{monitor_id}")
    assert get_resp.status_code == 404


async def test_cross_account_monitor_is_404_not_403(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)
    create_resp = await client.post("/api/v1/monitors", json=_PAYLOAD, headers=csrf_headers)
    monitor_id = create_resp.json()["id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as other_client:
        await login_as(other_client, db_session, app.state.clock)
        resp = await other_client.get(f"/api/v1/monitors/{monitor_id}")
        assert resp.status_code == 404

        other_csrf = await other_client.get("/api/v1/auth/csrf")
        headers = {"X-CSRF-Token": other_client.cookies.get("cronos_csrf")}
        assert other_csrf.status_code == 200
        delete_resp = await other_client.delete(
            f"/api/v1/monitors/{monitor_id}", headers=headers
        )
        assert delete_resp.status_code == 404


async def test_unverified_user_cannot_create_monitor(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock, verified=False)
    resp = await client.post("/api/v1/monitors", json=_PAYLOAD, headers=csrf_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "email_not_verified"


async def test_unverified_user_can_still_list_monitors(
    client: AsyncClient, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock, verified=False)
    resp = await client.get("/api/v1/monitors")
    assert resp.status_code == 200
    assert resp.json() == []
