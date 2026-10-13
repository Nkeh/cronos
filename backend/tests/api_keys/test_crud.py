from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.auth.api_keys_router as api_keys_router_module
from app.auth.models import ApiKey
from app.plans.config import get_plan
from tests.helpers import login_as


async def test_create_shows_key_once_and_sets_created_by(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    user = await login_as(client, db_session, app.state.clock)

    resp = await client.post(
        "/api/v1/api-keys",
        json={"name": "ci key", "scopes": ["monitors:read"]},
        headers=csrf_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["key"].startswith("cronos_")
    assert "key_hash" not in body

    list_resp = await client.get("/api/v1/api-keys")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1
    assert "key" not in list_resp.json()[0]
    assert "key_hash" not in list_resp.json()[0]

    row = (
        await db_session.execute(select(ApiKey).where(ApiKey.account_id == user.account_id))
    ).scalar_one()
    assert row.created_by_user_id == user.id


async def test_revoke_sets_revoked_at_and_is_idempotent(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)

    create_resp = await client.post(
        "/api/v1/api-keys",
        json={"name": "to revoke", "scopes": ["monitors:read"]},
        headers=csrf_headers,
    )
    key_id = create_resp.json()["id"]

    revoke_resp = await client.delete(f"/api/v1/api-keys/{key_id}", headers=csrf_headers)
    assert revoke_resp.status_code == 204

    list_resp = await client.get("/api/v1/api-keys")
    row = next(r for r in list_resp.json() if r["id"] == key_id)
    assert row["revoked_at"] is not None

    second_revoke = await client.delete(f"/api/v1/api-keys/{key_id}", headers=csrf_headers)
    assert second_revoke.status_code == 204


async def test_unknown_or_other_account_key_id_is_404(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)
    resp = await client.delete(
        "/api/v1/api-keys/00000000-0000-0000-0000-000000000000", headers=csrf_headers
    )
    assert resp.status_code == 404


async def test_prefix_collision_retries_then_succeeds(
    client: AsyncClient,
    csrf_headers: dict,
    db_session: AsyncSession,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await login_as(client, db_session, app.state.clock)

    real_generate = api_keys_router_module.generate_api_key
    full_key, prefix, key_hash = real_generate()

    # A pre-existing row holding that exact prefix, so the first two
    # generated-but-colliding attempts fail with a unique violation and the
    # third (a freshly generated, non-colliding prefix) succeeds.
    db_session.add(
        ApiKey(
            account_id=user.account_id,
            name="pre-existing",
            prefix=prefix,
            key_hash=key_hash,
            scopes=["monitors:read"],
        )
    )
    await db_session.commit()

    calls = {"n": 0}

    def _flaky_generate() -> tuple[str, str, str]:
        calls["n"] += 1
        if calls["n"] <= 2:
            return full_key, prefix, key_hash
        return real_generate()

    monkeypatch.setattr(api_keys_router_module, "generate_api_key", _flaky_generate)

    resp = await client.post(
        "/api/v1/api-keys",
        json={"name": "retry test", "scopes": ["monitors:read"]},
        headers=csrf_headers,
    )
    assert resp.status_code == 201
    assert calls["n"] == 3


async def test_eleventh_key_is_plan_limited(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)
    max_keys = get_plan("launch").max_api_keys

    for i in range(max_keys):
        resp = await client.post(
            "/api/v1/api-keys",
            json={"name": f"key-{i}", "scopes": ["monitors:read"]},
            headers=csrf_headers,
        )
        assert resp.status_code == 201

    over_limit = await client.post(
        "/api/v1/api-keys",
        json={"name": "one too many", "scopes": ["monitors:read"]},
        headers=csrf_headers,
    )
    assert over_limit.status_code == 422
    assert over_limit.json()["error"]["code"] == "plan_limit"
