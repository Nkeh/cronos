from __future__ import annotations

import uuid

from httpx import AsyncClient


def _unique_email() -> str:
    return f"pw-{uuid.uuid4().hex}@example.com"


async def test_rejects_password_too_short(client: AsyncClient, csrf_headers: dict) -> None:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": _unique_email(), "password": "short1"},
        headers=csrf_headers,
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "weak_password"
    assert body["error"]["field"] == "password"


async def test_rejects_password_too_long(client: AsyncClient, csrf_headers: dict) -> None:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": _unique_email(), "password": "x" * 129},
        headers=csrf_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "weak_password"


async def test_rejects_common_password(client: AsyncClient, csrf_headers: dict) -> None:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": _unique_email(), "password": "password123"},
        headers=csrf_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "weak_password"


async def test_accepts_valid_password(client: AsyncClient, csrf_headers: dict) -> None:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": _unique_email(), "password": "a-perfectly-fine-password"},
        headers=csrf_headers,
    )
    assert resp.status_code == 201
