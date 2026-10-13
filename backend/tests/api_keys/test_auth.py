from __future__ import annotations

import uuid

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_keys import generate_api_key
from app.auth.models import User
from tests.helpers import login_as, make_api_key

_MONITOR_PAYLOAD = {"name": "bearer-test", "url": "http://chaos:8000/health"}


async def _make_live_key(
    db_session: AsyncSession,
    account_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    scopes: list[str],
    **overrides,
) -> str:
    full_key, prefix, key_hash = generate_api_key()
    await make_api_key(
        db_session,
        account_id,
        prefix=prefix,
        key_hash=key_hash,
        scopes=scopes,
        created_by_user_id=created_by_user_id,
        **overrides,
    )
    await db_session.commit()
    return full_key


async def test_bearer_auth_works_without_csrf_header(
    client: AsyncClient, db_session: AsyncSession, app: FastAPI
) -> None:
    user = await login_as(client, db_session, app.state.clock)
    full_key = await _make_live_key(db_session, user.account_id, user.id, ["monitors:write"])
    client.cookies.clear()  # prove this isn't riding on the session cookie

    resp = await client.post(
        "/api/v1/monitors", json=_MONITOR_PAYLOAD, headers={"Authorization": f"Bearer {full_key}"}
    )
    assert resp.status_code == 201


async def test_revoked_key_is_401(
    client: AsyncClient, db_session: AsyncSession, app: FastAPI
) -> None:
    user = await login_as(client, db_session, app.state.clock)
    full_key = await _make_live_key(
        db_session, user.account_id, user.id, ["monitors:read"], revoked_at=app.state.clock.now()
    )
    client.cookies.clear()

    resp = await client.get(
        "/api/v1/monitors", headers={"Authorization": f"Bearer {full_key}"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_api_key"


async def test_malformed_bearer_is_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/monitors", headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_api_key"


async def test_garbage_bearer_with_valid_cookie_does_not_fall_back(
    client: AsyncClient, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)  # sets a valid session cookie

    resp = await client.get(
        "/api/v1/monitors", headers={"Authorization": "Bearer cronos_deadbeef_notreal"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_api_key"


async def test_read_only_scope_is_403_on_write(
    client: AsyncClient, db_session: AsyncSession, app: FastAPI
) -> None:
    user = await login_as(client, db_session, app.state.clock)
    full_key = await _make_live_key(db_session, user.account_id, user.id, ["monitors:read"])
    client.cookies.clear()

    resp = await client.post(
        "/api/v1/monitors", json=_MONITOR_PAYLOAD, headers={"Authorization": f"Bearer {full_key}"}
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "insufficient_scope"


async def test_api_key_cannot_manage_api_keys(
    client: AsyncClient, db_session: AsyncSession, app: FastAPI
) -> None:
    user = await login_as(client, db_session, app.state.clock)
    full_key = await _make_live_key(
        db_session, user.account_id, user.id, ["monitors:read", "monitors:write"]
    )
    client.cookies.clear()

    resp = await client.post(
        "/api/v1/api-keys",
        json={"name": "nope", "scopes": ["monitors:read"]},
        headers={"Authorization": f"Bearer {full_key}"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "session_required"


async def test_creator_deleted_key_is_401(
    client: AsyncClient, db_session: AsyncSession, app: FastAPI
) -> None:
    user = await login_as(client, db_session, app.state.clock)
    full_key = await _make_live_key(db_session, user.account_id, user.id, ["monitors:read"])

    await db_session.delete(await db_session.get(User, user.id))
    await db_session.commit()
    client.cookies.clear()

    resp = await client.get(
        "/api/v1/monitors", headers={"Authorization": f"Bearer {full_key}"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_api_key"
