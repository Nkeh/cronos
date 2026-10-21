from __future__ import annotations

import re
import uuid
from datetime import timedelta

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.security import hash_token, new_raw_token
from app.core.clock import SystemClock
from app.core.email import FakeEmailSender
from app.notifications.models import NotificationChannel
from tests.helpers import make_account, make_auth_token, make_user

VALID_PASSWORD = "correct-horse-battery-staple"


def _unique_email() -> str:
    return f"verify-{uuid.uuid4().hex}@example.com"


def _extract_token(text_body: str) -> str:
    match = re.search(r"token=(\S+)", text_body)
    assert match
    return match.group(1)


async def _signup_and_get_token(client: AsyncClient, app: FastAPI, csrf_headers: dict, email: str) -> str:
    resp = await client.post(
        "/api/v1/auth/signup", json={"email": email, "password": VALID_PASSWORD}, headers=csrf_headers
    )
    assert resp.status_code == 201
    sender: FakeEmailSender = app.state.email_sender
    message = next(m for m in sender.sent if m.to == email)
    return _extract_token(message.text_body)


async def test_verify_success_sets_email_verified_at(
    client: AsyncClient, csrf_headers: dict, app: FastAPI, db_session: AsyncSession
) -> None:
    email = _unique_email()
    token = await _signup_and_get_token(client, app, csrf_headers, email)

    resp = await client.post("/api/v1/auth/verify", json={"token": token}, headers=csrf_headers)
    assert resp.status_code == 200

    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    assert user.email_verified_at is not None


async def test_verify_success_creates_a_default_verified_email_channel(
    client: AsyncClient, csrf_headers: dict, app: FastAPI, db_session: AsyncSession
) -> None:
    """Day 9, confirmed with Oryn: verifying the account email auto-creates a verified `email`
    channel for that address with is_default=true."""
    email = _unique_email()
    token = await _signup_and_get_token(client, app, csrf_headers, email)

    resp = await client.post("/api/v1/auth/verify", json={"token": token}, headers=csrf_headers)
    assert resp.status_code == 200

    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    channel = (
        await db_session.execute(
            select(NotificationChannel).where(NotificationChannel.account_id == user.account_id)
        )
    ).scalar_one()
    assert channel.kind == "email"
    assert channel.config == {"address": email}
    assert channel.is_default is True
    assert channel.verified_at is not None


async def test_verify_replay_rejected(client: AsyncClient, csrf_headers: dict, app: FastAPI) -> None:
    email = _unique_email()
    token = await _signup_and_get_token(client, app, csrf_headers, email)

    first = await client.post("/api/v1/auth/verify", json={"token": token}, headers=csrf_headers)
    assert first.status_code == 200

    second = await client.post("/api/v1/auth/verify", json={"token": token}, headers=csrf_headers)
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "invalid_token"


async def test_verify_expired_rejected(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession
) -> None:
    account = await make_account(db_session)
    user = await make_user(db_session, account.id)
    raw_token = new_raw_token()
    await make_auth_token(
        db_session,
        user.id,
        purpose="verify_email",
        token_hash=hash_token(raw_token),
        expires_at=SystemClock().now() - timedelta(hours=1),
    )
    await db_session.commit()

    resp = await client.post("/api/v1/auth/verify", json={"token": raw_token}, headers=csrf_headers)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_token"


async def test_verify_wrong_purpose_rejected(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession
) -> None:
    """A reset token used against /verify must be rejected, same as any
    other invalid token — no enumeration of why."""
    account = await make_account(db_session)
    user = await make_user(db_session, account.id)
    raw_token = new_raw_token()
    await make_auth_token(
        db_session,
        user.id,
        purpose="reset_password",
        token_hash=hash_token(raw_token),
        expires_at=SystemClock().now() + timedelta(hours=1),
    )
    await db_session.commit()

    resp = await client.post("/api/v1/auth/verify", json={"token": raw_token}, headers=csrf_headers)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_token"


async def test_verify_resend_requires_auth(client: AsyncClient, csrf_headers: dict) -> None:
    resp = await client.post("/api/v1/auth/verify/resend", json={}, headers=csrf_headers)
    assert resp.status_code == 401


async def test_verify_resend_rate_limited(client: AsyncClient, csrf_headers: dict, app: FastAPI) -> None:
    email = _unique_email()
    await client.post(
        "/api/v1/auth/signup", json={"email": email, "password": VALID_PASSWORD}, headers=csrf_headers
    )
    login_resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": VALID_PASSWORD}, headers=csrf_headers
    )
    assert login_resp.status_code == 200
    # login rotates the CSRF cookie — the header captured before login is stale now
    csrf_headers = {"X-CSRF-Token": client.cookies.get("cronos_csrf")}

    settings = app.state.settings
    for _ in range(settings.rate_limit_verify_resend_user_max):
        resp = await client.post("/api/v1/auth/verify/resend", json={}, headers=csrf_headers)
        assert resp.status_code == 200

    resp = await client.post("/api/v1/auth/verify/resend", json={}, headers=csrf_headers)
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
