from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.clock import SystemClock
from app.core.config import get_settings
from app.core.email import FakeEmailSender
from app.core.redis import FailOpenRedis
from app.main import create_app


def _unique_email() -> str:
    return f"ratelimit-{uuid.uuid4().hex}@example.com"


async def test_429_includes_retry_after(client: AsyncClient, csrf_headers: dict, app: FastAPI) -> None:
    settings = app.state.settings
    for _ in range(settings.rate_limit_login_ip_max):
        await client.post(
            "/api/v1/auth/login",
            json={"email": _unique_email(), "password": "whatever-password-1"},
            headers=csrf_headers,
        )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": _unique_email(), "password": "whatever-password-1"},
        headers=csrf_headers,
    )
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) > 0


async def test_redis_down_still_allows_request_and_logs_once_per_outage(
    client: AsyncClient, csrf_headers: dict, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real outage fails every Redis operation identically (connection
    refused), not just one — breaking only incr_with_ttl's script while
    get/ttl/delete keep succeeding would let those successes flip the
    breaker back to "up" between calls, which doesn't reflect a real
    outage and isn't what "one warning per episode" is meant to cover.
    """
    redis: FailOpenRedis = app.state.redis

    class _BrokenClient:
        async def get(self, *a, **kw):
            raise RedisConnectionError("simulated outage")

        async def ttl(self, *a, **kw):
            raise RedisConnectionError("simulated outage")

        async def delete(self, *a, **kw):
            raise RedisConnectionError("simulated outage")

    async def broken_script(keys=None, args=None, **kwargs):
        raise RedisConnectionError("simulated outage")

    monkeypatch.setattr(redis, "_client", _BrokenClient())
    monkeypatch.setattr(redis, "_incr_with_ttl_script", broken_script)

    warnings: list[str] = []
    monkeypatch.setattr("app.core.redis.logger.warning", lambda event, **kw: warnings.append(event))

    resp1 = await client.post(
        "/api/v1/auth/login",
        json={"email": _unique_email(), "password": "whatever-password-1"},
        headers=csrf_headers,
    )
    assert resp1.status_code == 401  # reached the real auth check — not blocked by rate limiting

    resp2 = await client.post(
        "/api/v1/auth/login",
        json={"email": _unique_email(), "password": "whatever-password-1"},
        headers=csrf_headers,
    )
    assert resp2.status_code == 401

    assert warnings.count("redis_unavailable") == 1  # one warning per outage episode, not per call


async def test_rate_limit_key_always_has_a_ttl(app: FastAPI) -> None:
    redis: FailOpenRedis = app.state.redis
    key = f"ratelimit:test:{uuid.uuid4().hex}"

    result = await redis.incr_with_ttl(key, 60)
    assert result is not None
    count, ttl = result
    assert count == 1
    assert ttl > 0

    raw_ttl = await redis.get_ttl(key)
    assert raw_ttl is not None and raw_ttl > 0


async def test_x_forwarded_for_ignored_from_untrusted_source(
    client: AsyncClient, csrf_headers: dict, app: FastAPI
) -> None:
    settings = app.state.settings
    assert "127.0.0.1" not in settings.trusted_proxy_ips_set  # Caddy's real pinned address is active

    for i in range(settings.rate_limit_login_ip_max):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": _unique_email(), "password": "whatever-password-1"},
            headers={**csrf_headers, "X-Forwarded-For": f"203.0.113.{i + 1}"},
        )
        assert resp.status_code == 401

    # if the (different every time) spoofed header had been honored, this
    # would look like a fresh, never-seen IP and be allowed; since it's
    # ignored, the real (untrusted) peer identity is used, already at its cap.
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": _unique_email(), "password": "whatever-password-1"},
        headers={**csrf_headers, "X-Forwarded-For": "203.0.113.250"},
    )
    assert resp.status_code == 429


async def test_x_forwarded_for_honored_from_trusted_source() -> None:
    settings = get_settings().model_copy(update={"trusted_proxy_ips": "127.0.0.1"})
    application = create_app(settings=settings, clock=SystemClock(), email_sender=FakeEmailSender())
    async with application.router.lifespan_context(application):
        async with AsyncClient(transport=ASGITransport(app=application), base_url="http://testserver") as c:
            await c.get("/api/v1/auth/csrf")
            headers = {"X-CSRF-Token": c.cookies.get("cronos_csrf")}

            # same trusted peer every time, but each request claims a
            # DIFFERENT forwarded IP — if honored, none share a rate-limit
            # bucket, so every one of these (more than the per-IP cap)
            # succeeds past the check.
            for i in range(settings.rate_limit_login_ip_max + 5):
                resp = await c.post(
                    "/api/v1/auth/login",
                    json={"email": _unique_email(), "password": "whatever-password-1"},
                    headers={**headers, "X-Forwarded-For": f"198.51.100.{i + 1}"},
                )
                assert resp.status_code == 401
