from __future__ import annotations

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Session, User
from app.auth.security import hash_token
from tests.helpers import make_account, make_user_with_password

VALID_PASSWORD = "correct-horse-battery-staple"


async def _login(client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI) -> User:
    account = await make_account(db_session)
    user = await make_user_with_password(db_session, account.id, VALID_PASSWORD, app.state.password_hasher)
    await db_session.commit()
    resp = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": VALID_PASSWORD}, headers=csrf_headers
    )
    assert resp.status_code == 200
    return user


async def test_logout_deletes_session_row(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await _login(client, csrf_headers, db_session, app)
    raw_token = client.cookies.get("cronos_session")
    token_hash = hash_token(raw_token)

    headers = {"X-CSRF-Token": client.cookies.get("cronos_csrf")}
    resp = await client.post("/api/v1/auth/logout", json={}, headers=headers)
    assert resp.status_code == 204

    row = await db_session.get(Session, token_hash)
    assert row is None


async def test_logout_clears_cookies_and_rotates_csrf(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await _login(client, csrf_headers, db_session, app)
    old_csrf = client.cookies.get("cronos_csrf")
    headers = {"X-CSRF-Token": old_csrf}

    resp = await client.post("/api/v1/auth/logout", json={}, headers=headers)
    assert resp.status_code == 204

    set_cookie_headers = resp.headers.get_list("set-cookie")
    session_clear = next(h for h in set_cookie_headers if h.startswith("cronos_session="))
    assert "Max-Age=0" in session_clear

    assert client.cookies.get("cronos_csrf") != old_csrf

    me_resp = await client.get("/api/v1/auth/me")
    assert me_resp.status_code == 401
