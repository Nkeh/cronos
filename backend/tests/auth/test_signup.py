from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import Account
from app.auth.models import User
from app.core.email import FakeEmailSender

VALID_PASSWORD = "correct-horse-battery-staple"


def _unique_email() -> str:
    return f"signup-{uuid.uuid4().hex}@example.com"


async def test_signup_creates_account_and_user(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession
) -> None:
    email = _unique_email()
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": VALID_PASSWORD},
        headers=csrf_headers,
    )
    assert resp.status_code == 201
    assert resp.json() == {"message": "Check your email to verify your account."}

    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    assert user.email_verified_at is None
    account = await db_session.get(Account, user.account_id)
    assert account.plan == "launch"


async def test_signup_sends_verification_email(client: AsyncClient, csrf_headers: dict, app: FastAPI) -> None:
    email = _unique_email()
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": VALID_PASSWORD},
        headers=csrf_headers,
    )
    assert resp.status_code == 201

    sender: FakeEmailSender = app.state.email_sender
    sent = [m for m in sender.sent if m.to == email]
    assert len(sent) == 1
    assert "verify" in sent[0].subject.lower()


async def test_signup_duplicate_email_returns_identical_response(
    client: AsyncClient, csrf_headers: dict
) -> None:
    email = _unique_email()
    first = await client.post(
        "/api/v1/auth/signup", json={"email": email, "password": VALID_PASSWORD}, headers=csrf_headers
    )
    second = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "a-different-password-1"},
        headers=csrf_headers,
    )
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()


async def test_signup_duplicate_email_sends_notice_not_verification(
    client: AsyncClient, csrf_headers: dict, app: FastAPI
) -> None:
    email = _unique_email()
    await client.post(
        "/api/v1/auth/signup", json={"email": email, "password": VALID_PASSWORD}, headers=csrf_headers
    )
    sender: FakeEmailSender = app.state.email_sender
    sender.sent.clear()

    await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "a-different-password-2"},
        headers=csrf_headers,
    )
    sent = [m for m in sender.sent if m.to == email]
    assert len(sent) == 1
    assert "tried to register" in sent[0].subject.lower()
    assert "verify" not in sent[0].subject.lower()


async def test_signup_duplicate_email_runs_comparable_argon2_work(
    client: AsyncClient, csrf_headers: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both branches must call hash_password exactly once — proven by call
    count, not wall-clock timing (which would be flaky). A missing dummy
    hash on the duplicate branch would make the two counts diverge."""
    import app.auth.router as router_module

    calls = 0
    original = router_module.hash_password

    async def counting_hash_password(hasher, password):
        nonlocal calls
        calls += 1
        return await original(hasher, password)

    monkeypatch.setattr(router_module, "hash_password", counting_hash_password)

    email = _unique_email()
    await client.post(
        "/api/v1/auth/signup", json={"email": email, "password": VALID_PASSWORD}, headers=csrf_headers
    )
    assert calls == 1

    await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "a-different-password-3"},
        headers=csrf_headers,
    )
    assert calls == 2
