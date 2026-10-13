from __future__ import annotations

import re
import uuid

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email import FakeEmailSender
from tests.helpers import make_account, make_user_with_password

VALID_PASSWORD = "correct-horse-battery-staple"
NEW_PASSWORD = "a-brand-new-password-99"


def _unique_email() -> str:
    return f"reset-{uuid.uuid4().hex}@example.com"


def _extract_token(text_body: str) -> str:
    match = re.search(r"token=(\S+)", text_body)
    assert match
    return match.group(1)


async def test_reset_request_always_202(client: AsyncClient, csrf_headers: dict) -> None:
    resp = await client.post(
        "/api/v1/auth/reset-request", json={"email": _unique_email()}, headers=csrf_headers
    )
    assert resp.status_code == 202


async def test_reset_request_sends_email_only_if_user_exists(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    sender: FakeEmailSender = app.state.email_sender

    unknown_email = _unique_email()
    resp = await client.post("/api/v1/auth/reset-request", json={"email": unknown_email}, headers=csrf_headers)
    assert resp.status_code == 202
    assert not any(m.to == unknown_email for m in sender.sent)

    account = await make_account(db_session)
    user = await make_user_with_password(db_session, account.id, VALID_PASSWORD, app.state.password_hasher)
    await db_session.commit()

    resp = await client.post("/api/v1/auth/reset-request", json={"email": user.email}, headers=csrf_headers)
    assert resp.status_code == 202
    assert any(m.to == user.email for m in sender.sent)


async def test_reset_kills_every_session_and_rejects_old_password(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    account = await make_account(db_session)
    user = await make_user_with_password(db_session, account.id, VALID_PASSWORD, app.state.password_hasher)
    await db_session.commit()

    # two active sessions, via two independent cookie jars against the same app
    login_a = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": VALID_PASSWORD}, headers=csrf_headers
    )
    assert login_a.status_code == 200
    session_a_cookie = client.cookies.get("cronos_session")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client_b:
        await client_b.get("/api/v1/auth/csrf")
        headers_b = {"X-CSRF-Token": client_b.cookies.get("cronos_csrf")}
        login_b = await client_b.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": VALID_PASSWORD},
            headers=headers_b,
        )
        assert login_b.status_code == 200
        session_b_cookie = client_b.cookies.get("cronos_session")
        assert session_b_cookie != session_a_cookie

        sender: FakeEmailSender = app.state.email_sender
        headers_a = {"X-CSRF-Token": client.cookies.get("cronos_csrf")}
        reset_request = await client.post(
            "/api/v1/auth/reset-request", json={"email": user.email}, headers=headers_a
        )
        assert reset_request.status_code == 202
        message = next(m for m in sender.sent if m.to == user.email)
        token = _extract_token(message.text_body)

        headers_a = {"X-CSRF-Token": client.cookies.get("cronos_csrf")}
        reset_resp = await client.post(
            "/api/v1/auth/reset", json={"token": token, "password": NEW_PASSWORD}, headers=headers_a
        )
        assert reset_resp.status_code == 200

        # both sessions are now dead
        client.cookies.set("cronos_session", session_a_cookie)
        assert (await client.get("/api/v1/auth/me")).status_code == 401

        client_b.cookies.set("cronos_session", session_b_cookie)
        assert (await client_b.get("/api/v1/auth/me")).status_code == 401

        # old password fails, new one works
        headers_a = {"X-CSRF-Token": client.cookies.get("cronos_csrf")}
        old_login = await client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": VALID_PASSWORD}, headers=headers_a
        )
        assert old_login.status_code == 401

        new_login = await client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": NEW_PASSWORD}, headers=headers_a
        )
        assert new_login.status_code == 200

        # replay rejected
        headers_a = {"X-CSRF-Token": client.cookies.get("cronos_csrf")}
        replay = await client.post(
            "/api/v1/auth/reset", json={"token": token, "password": "yet-another-password-1"}, headers=headers_a
        )
        assert replay.status_code == 400
        assert replay.json()["error"]["code"] == "invalid_token"


async def test_reset_request_rate_limited_by_email(client: AsyncClient, csrf_headers: dict, app: FastAPI) -> None:
    settings = app.state.settings
    email = _unique_email()
    for _ in range(settings.rate_limit_reset_request_email_max):
        resp = await client.post("/api/v1/auth/reset-request", json={"email": email}, headers=csrf_headers)
        assert resp.status_code == 202
    resp = await client.post("/api/v1/auth/reset-request", json={"email": email}, headers=csrf_headers)
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


async def test_reset_request_rate_limited_by_ip(client: AsyncClient, csrf_headers: dict, app: FastAPI) -> None:
    settings = app.state.settings
    for _ in range(settings.rate_limit_reset_request_ip_max):
        resp = await client.post(
            "/api/v1/auth/reset-request", json={"email": _unique_email()}, headers=csrf_headers
        )
        assert resp.status_code == 202
    resp = await client.post(
        "/api/v1/auth/reset-request", json={"email": _unique_email()}, headers=csrf_headers
    )
    assert resp.status_code == 429
