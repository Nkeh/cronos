from __future__ import annotations

from httpx import AsyncClient


async def test_missing_csrf_header_rejected(client: AsyncClient) -> None:
    await client.get("/api/v1/auth/csrf")  # sets the cookie; we deliberately don't send the header
    resp = await client.post(
        "/api/v1/auth/signup", json={"email": "x@example.com", "password": "whatever-password-1"}
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "csrf_failed"


async def test_mismatched_csrf_header_rejected(client: AsyncClient) -> None:
    await client.get("/api/v1/auth/csrf")
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": "x@example.com", "password": "whatever-password-1"},
        headers={"X-CSRF-Token": "not-the-real-token"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "csrf_failed"


async def test_bad_origin_rejected(client: AsyncClient, csrf_headers: dict) -> None:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": "x@example.com", "password": "whatever-password-1"},
        headers={**csrf_headers, "Origin": "https://evil.example"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "origin_rejected"


async def test_wrong_content_type_rejected(client: AsyncClient, csrf_headers: dict) -> None:
    resp = await client.post(
        "/api/v1/auth/signup",
        content=b"email=x@example.com&password=whatever-password-1",
        headers={**csrf_headers, "Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 415
    assert resp.json()["error"]["code"] == "unsupported_media_type"


async def test_api_key_placeholder_exempt_from_csrf(client: AsyncClient) -> None:
    """No CSRF cookie/header sent at all, but an Authorization header makes
    CSRFMiddleware skip the check entirely (Day 4 placeholder) — the request
    still fails (no real API-key auth exists yet, and no session cookie
    either) but via current_user's plain 401, never csrf_failed."""
    resp = await client.post(
        "/api/v1/auth/logout", json={}, headers={"Authorization": "Bearer placeholder-key"}
    )
    assert resp.status_code == 401
