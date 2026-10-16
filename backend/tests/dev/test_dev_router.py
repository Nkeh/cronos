from __future__ import annotations

import os
import re
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.clock import SystemClock
from app.core.config import ConfigurationError, Settings
from app.core.email import FakeEmailSender
from app.main import create_app


async def test_dev_create_user_then_seed_monitors(
    client: AsyncClient, csrf_headers: dict[str, str]
) -> None:
    email = f"dev-router-{uuid.uuid4().hex[:8]}@example.com"

    create_resp = await client.post(
        "/api/v1/_dev/users",
        json={"email": email, "password": "CorrectHorseBattery9", "verified": True},
        headers=csrf_headers,
    )
    assert create_resp.status_code == 201
    body = create_resp.json()
    assert body["email"] == email

    seed_resp = await client.post(
        "/api/v1/_dev/seed-monitors", json={"email": email, "count": 2}, headers=csrf_headers
    )
    assert seed_resp.status_code == 201
    assert seed_resp.json()["created"] == 2


async def test_dev_create_user_duplicate_email_is_conflict(
    client: AsyncClient, csrf_headers: dict[str, str]
) -> None:
    email = f"dev-router-{uuid.uuid4().hex[:8]}@example.com"
    payload = {"email": email, "password": "CorrectHorseBattery9", "verified": False}

    first = await client.post("/api/v1/_dev/users", json=payload, headers=csrf_headers)
    assert first.status_code == 201

    second = await client.post("/api/v1/_dev/users", json=payload, headers=csrf_headers)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "dev_fixture_conflict"


async def test_dev_delete_user_is_idempotent_and_cascades(
    client: AsyncClient, csrf_headers: dict[str, str]
) -> None:
    email = f"dev-router-{uuid.uuid4().hex[:8]}@example.com"
    await client.post(
        "/api/v1/_dev/users",
        json={"email": email, "password": "CorrectHorseBattery9", "verified": True},
        headers=csrf_headers,
    )
    await client.post(
        "/api/v1/_dev/seed-monitors", json={"email": email, "count": 1}, headers=csrf_headers
    )

    first_delete = await client.post(
        "/api/v1/_dev/users/delete", json={"email": email}, headers=csrf_headers
    )
    assert first_delete.status_code == 204

    # Idempotent: deleting an email that's already gone (or never existed) is still a 204.
    second_delete = await client.post(
        "/api/v1/_dev/users/delete", json={"email": email}, headers=csrf_headers
    )
    assert second_delete.status_code == 204

    # Recreating the same email now succeeds — proof the account (and its monitor, via cascade)
    # was actually removed, not just hidden.
    recreate = await client.post(
        "/api/v1/_dev/users",
        json={"email": email, "password": "CorrectHorseBattery9", "verified": True},
        headers=csrf_headers,
    )
    assert recreate.status_code == 201


async def _assert_dev_router_absent(settings: Settings) -> None:
    app: FastAPI = create_app(settings=settings, clock=SystemClock(), email_sender=FakeEmailSender())

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            # GET bypasses CSRFMiddleware (state-changing methods only) — fetch a valid token
            # first so the POST below 404s because the route doesn't exist, not because CSRF
            # failed first.
            csrf_resp = await c.get("/api/v1/auth/csrf")
            assert csrf_resp.status_code == 200
            token = re.search(r"cronos_csrf=([^;]+)", csrf_resp.headers["set-cookie"]).group(1)

            resp = await c.post(
                "/api/v1/_dev/users",
                json={"email": "x@example.com", "password": "x"},
                headers={"X-CSRF-Token": token, "Cookie": f"cronos_csrf={token}"},
            )
            assert resp.status_code == 404


def test_production_refuses_to_start_with_probe_kind_stub() -> None:
    """Day 6 added PROBE_KIND as Literal["stub"] only, so a production Settings object was
    unconditionally rejected (stub always reports "up", which must never run in production).
    Day 7 widens PROBE_KIND to Literal["stub", "http"] and flips the default to "http", so a
    production app now starts cleanly by default (see test_dev_router_not_mounted_in_production
    below) -- PROBE_KIND=stub in production is a *deliberate* misconfiguration now, not the only
    possible state, but it must still refuse to start forever."""
    settings = Settings(
        database_url=os.environ["DATABASE_URL"],
        env="production",
        secret_key="a-real-production-secret-key-not-the-dev-placeholder",
        encryption_key="a-real-production-secret-key-not-the-dev-placeholder",
        cookie_secure=True,
        debug=False,
        ssrf_allow_hosts=None,
        probe_kind="stub",
    )
    with pytest.raises(ConfigurationError, match="PROBE_KIND"):
        create_app(settings=settings, clock=SystemClock(), email_sender=FakeEmailSender())


async def test_dev_router_not_mounted_in_production() -> None:
    """The real, originally-intended test (restored per Day 6's own DAY 7 TODO note): with the
    now-production-safe default probe_kind ("http"), create_app() succeeds for a production
    Settings object, and the dev-only router must still be absent from it."""
    settings = Settings(
        database_url=os.environ["DATABASE_URL"],
        env="production",
        secret_key="a-real-production-secret-key-not-the-dev-placeholder",
        encryption_key="a-real-production-secret-key-not-the-dev-placeholder",
        cookie_secure=True,
        debug=False,
        ssrf_allow_hosts=None,
    )
    await _assert_dev_router_absent(settings)


async def test_dev_router_not_mounted_under_test_env() -> None:
    settings = Settings(database_url=os.environ["DATABASE_URL"], env="test")
    await _assert_dev_router_absent(settings)
