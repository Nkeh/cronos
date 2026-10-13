from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from argon2 import PasswordHasher as RealPasswordHasher
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import SystemClock
from app.core.config import get_settings
from app.core.email import FakeEmailSender
from app.main import create_app
from tests.helpers import make_account, make_user, make_user_with_password

VALID_PASSWORD = "correct-horse-battery-staple"


def _unique_email() -> str:
    return f"login-{uuid.uuid4().hex}@example.com"


async def _fresh_csrf(client: AsyncClient) -> dict[str, str]:
    resp = await client.get("/api/v1/auth/csrf")
    assert resp.status_code == 200
    return {"X-CSRF-Token": client.cookies.get("cronos_csrf")}


# ---- cookie flags / rotation -------------------------------------------------


async def test_login_success_sets_cookies_with_correct_flags(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    account = await make_account(db_session)
    user = await make_user_with_password(db_session, account.id, VALID_PASSWORD, app.state.password_hasher)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": VALID_PASSWORD}, headers=csrf_headers
    )
    assert resp.status_code == 200

    set_cookie_headers = resp.headers.get_list("set-cookie")
    session_cookie = next(h for h in set_cookie_headers if h.startswith("cronos_session="))
    csrf_cookie = next(h for h in set_cookie_headers if h.startswith("cronos_csrf="))

    assert "HttpOnly" in session_cookie
    assert "samesite=lax" in session_cookie.lower()
    assert "HttpOnly" not in csrf_cookie
    assert "samesite=lax" in csrf_cookie.lower()


async def test_login_rotates_csrf_cookie(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    account = await make_account(db_session)
    user = await make_user_with_password(db_session, account.id, VALID_PASSWORD, app.state.password_hasher)
    await db_session.commit()

    old_csrf = client.cookies.get("cronos_csrf")
    resp = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": VALID_PASSWORD}, headers=csrf_headers
    )
    assert resp.status_code == 200
    assert client.cookies.get("cronos_csrf") != old_csrf


# ---- identical failure responses / dummy hash --------------------------------


async def test_login_wrong_password_and_unknown_email_are_identical(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    account = await make_account(db_session)
    user = await make_user_with_password(db_session, account.id, VALID_PASSWORD, app.state.password_hasher)
    await db_session.commit()

    wrong_password = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "totally-wrong-1"}, headers=csrf_headers
    )
    unknown_email = await client.post(
        "/api/v1/auth/login",
        json={"email": _unique_email(), "password": "totally-wrong-1"},
        headers=csrf_headers,
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


async def test_login_unknown_email_runs_dummy_hash_verify(
    client: AsyncClient, csrf_headers: dict, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.auth.router as router_module

    calls: list[str] = []
    original = router_module.verify_password

    async def spy(hasher, stored_hash, password):
        calls.append(stored_hash)
        return await original(hasher, stored_hash, password)

    monkeypatch.setattr(router_module, "verify_password", spy)

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": _unique_email(), "password": "whatever-password-1"},
        headers=csrf_headers,
    )
    assert resp.status_code == 401
    assert calls == [app.state.dummy_password_hash]


# ---- rehash / unverified ------------------------------------------------------


async def test_login_rehashes_when_params_changed(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession
) -> None:
    strong_hasher = RealPasswordHasher()  # real library defaults, different from test's cheap params
    account = await make_account(db_session)
    user = await make_user(db_session, account.id, password_hash=strong_hasher.hash(VALID_PASSWORD))
    await db_session.commit()
    old_hash = user.password_hash

    resp = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": VALID_PASSWORD}, headers=csrf_headers
    )
    assert resp.status_code == 200

    await db_session.refresh(user)
    assert user.password_hash != old_hash


async def test_login_unverified_user_can_log_in(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    account = await make_account(db_session)
    user = await make_user_with_password(db_session, account.id, VALID_PASSWORD, app.state.password_hasher)
    await db_session.commit()
    assert user.email_verified_at is None

    resp = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": VALID_PASSWORD}, headers=csrf_headers
    )
    assert resp.status_code == 200
    assert resp.json()["email_verified"] is False


# ---- per-IP limit (every attempt) --------------------------------------------


async def test_login_per_ip_limit(client: AsyncClient, csrf_headers: dict, app: FastAPI) -> None:
    settings = app.state.settings
    for _ in range(settings.rate_limit_login_ip_max):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": _unique_email(), "password": "whatever-password-1"},
            headers=csrf_headers,
        )
        assert resp.status_code == 401

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": _unique_email(), "password": "whatever-password-1"},
        headers=csrf_headers,
    )
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


# ---- failure-only ceilings, requiring simulated distinct client IPs ---------
# ASGITransport's peer is always the same address, so these use an app whose
# trusted_proxy_ips includes that peer, making X-Forwarded-For spoofable
# on purpose, for the test only — the shared `app`/`client` fixtures keep the
# real TRUSTED_PROXY_IPS (Caddy's pinned address) and are unaffected.


@pytest_asyncio.fixture
async def ip_spoofable_app():
    settings = get_settings().model_copy(update={"trusted_proxy_ips": "127.0.0.1"})
    application = create_app(settings=settings, clock=SystemClock(), email_sender=FakeEmailSender())
    async with application.router.lifespan_context(application):
        yield application


async def test_login_email_ip_failure_limit_blocks_attacker_not_victim(
    ip_spoofable_app: FastAPI, db_session: AsyncSession
) -> None:
    settings = ip_spoofable_app.state.settings
    account = await make_account(db_session)
    user = await make_user_with_password(
        db_session, account.id, VALID_PASSWORD, ip_spoofable_app.state.password_hasher
    )
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=ip_spoofable_app), base_url="http://testserver"
    ) as attacker, AsyncClient(
        transport=ASGITransport(app=ip_spoofable_app), base_url="http://testserver"
    ) as victim:
        attacker_headers = await _fresh_csrf(attacker)
        victim_headers = await _fresh_csrf(victim)
        attacker_ip, victim_ip = "10.0.0.50", "10.0.0.99"

        for _ in range(settings.rate_limit_login_email_ip_failures_max):
            resp = await attacker.post(
                "/api/v1/auth/login",
                json={"email": user.email, "password": "attacker-guess"},
                headers={**attacker_headers, "X-Forwarded-For": attacker_ip},
            )
            assert resp.status_code == 401

        blocked = await attacker.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "attacker-guess"},
            headers={**attacker_headers, "X-Forwarded-For": attacker_ip},
        )
        assert blocked.status_code == 429

        # the victim, logging in correctly from their OWN IP, is unaffected
        victim_resp = await victim.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": VALID_PASSWORD},
            headers={**victim_headers, "X-Forwarded-For": victim_ip},
        )
        assert victim_resp.status_code == 200


async def test_login_per_email_failure_ceiling_across_many_ips(
    ip_spoofable_app: FastAPI, db_session: AsyncSession
) -> None:
    settings = ip_spoofable_app.state.settings
    account = await make_account(db_session)
    user = await make_user_with_password(
        db_session, account.id, VALID_PASSWORD, ip_spoofable_app.state.password_hasher
    )
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=ip_spoofable_app), base_url="http://testserver"
    ) as c:
        headers = await _fresh_csrf(c)
        max_failures = settings.rate_limit_login_email_failures_max

        # one unique IP per failure, so the (email, IP) 5-failure ceiling
        # never trips — only the per-email/all-IPs ceiling should.
        for i in range(max_failures):
            resp = await c.post(
                "/api/v1/auth/login",
                json={"email": user.email, "password": "distributed-guess"},
                headers={**headers, "X-Forwarded-For": f"10.1.0.{i + 1}"},
            )
            assert resp.status_code == 401

        resp = await c.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "distributed-guess"},
            headers={**headers, "X-Forwarded-For": "10.2.0.1"},
        )
        assert resp.status_code == 429


async def test_login_success_resets_email_ip_failure_counter(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    account = await make_account(db_session)
    user = await make_user_with_password(db_session, account.id, VALID_PASSWORD, app.state.password_hasher)
    await db_session.commit()

    settings = app.state.settings
    almost_limit = settings.rate_limit_login_email_ip_failures_max - 1

    headers = csrf_headers
    for _ in range(almost_limit):
        resp = await client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": "wrong-a"}, headers=headers
        )
        assert resp.status_code == 401

    success = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": VALID_PASSWORD}, headers=headers
    )
    assert success.status_code == 200

    # the CSRF cookie rotated on that successful login — refresh the header
    headers = {"X-CSRF-Token": client.cookies.get("cronos_csrf")}

    for _ in range(almost_limit):
        resp = await client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": "wrong-b"}, headers=headers
        )
        assert resp.status_code == 401  # not 429 — the success above reset this counter
