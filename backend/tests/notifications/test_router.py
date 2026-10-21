"""Channels API tests. Webhook verify/test-send tests talk to the LIVE chaos container (reachable
as host "chaos" on the Compose default network) -- same convention as
tests/engine/test_http_probe_chaos.py and tests/notifier/test_webhook.py.
"""

from __future__ import annotations

import uuid

import httpx
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_keys import generate_api_key
from app.notifications.models import NotificationChannel
from app.plans.config import get_plan
from tests.helpers import login_as, make_api_key, make_notification, make_notification_channel

_EMAIL_PAYLOAD = {"kind": "email", "name": "ops inbox", "config": {"address": "ops@example.com"}}
# chaos's /webhook route is a single fixed path (unlike its GET/HEAD target routes, which accept
# any path) -- every webhook test below shares it. POST /_control resets its response-sequence
# cursor on every call, so tests stay independent despite the shared path.
_WEBHOOK_URL = "http://chaos:8000/webhook"


def _webhook_payload(url: str = _WEBHOOK_URL, **overrides) -> dict:
    payload = {"kind": "webhook", "name": "ops webhook", "config": {"url": url}}
    payload.update(overrides)
    return payload


@pytest_asyncio.fixture
async def chaos_control():
    async with httpx.AsyncClient(base_url="http://chaos:8000", trust_env=False, timeout=5) as client:

        async def _set(**fields) -> dict:
            body = {"path": "/webhook", "mode": fields.pop("mode", "up"), **fields}
            resp = await client.post("/_control", json=body)
            resp.raise_for_status()
            return resp.json()

        yield _set


@pytest_asyncio.fixture
async def chaos_log():
    async with httpx.AsyncClient(base_url="http://chaos:8000", trust_env=False, timeout=5) as client:

        async def _tail() -> list[dict]:
            resp = await client.get("/_webhook/_log")
            resp.raise_for_status()
            return resp.json()

        yield _tail


# ---- CRUD ----


async def test_create_list_patch_delete_email_channel(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)

    create_resp = await client.post("/api/v1/channels", json=_EMAIL_PAYLOAD, headers=csrf_headers)
    assert create_resp.status_code == 201
    body = create_resp.json()
    assert body["kind"] == "email"
    assert body["config"] == {"address": "ops@example.com"}
    assert body["verified_at"] is None
    assert "secret" not in body
    channel_id = body["id"]

    list_resp = await client.get("/api/v1/channels")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    patch_resp = await client.patch(
        f"/api/v1/channels/{channel_id}", json={"name": "renamed"}, headers=csrf_headers
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["name"] == "renamed"

    delete_resp = await client.delete(f"/api/v1/channels/{channel_id}", headers=csrf_headers)
    assert delete_resp.status_code == 204
    assert (await client.get("/api/v1/channels")).json() == []


async def test_create_webhook_channel_generates_and_hides_a_secret(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    user = await login_as(client, db_session, app.state.clock)
    resp = await client.post(
        "/api/v1/channels", json=_webhook_payload("http://chaos:8000/webhook"), headers=csrf_headers
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "secret" not in body

    row = (
        await db_session.execute(select(NotificationChannel).where(NotificationChannel.account_id == user.account_id))
    ).scalar_one()
    assert row.secret is not None


async def test_rejects_a_private_webhook_url(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)
    resp = await client.post(
        "/api/v1/channels",
        json=_webhook_payload("http://169.254.169.254/latest/meta-data/"),
        headers=csrf_headers,
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["field"] == "config.url"


async def test_rejects_an_invalid_email_address(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)
    resp = await client.post(
        "/api/v1/channels",
        json={"kind": "email", "name": "x", "config": {"address": "not-an-email"}},
        headers=csrf_headers,
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["field"] == "config.address"


async def test_max_channels_limit_is_enforced(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)
    limit = get_plan("launch").max_channels
    for i in range(limit):
        resp = await client.post(
            "/api/v1/channels",
            json={"kind": "email", "name": f"c{i}", "config": {"address": f"c{i}@example.com"}},
            headers=csrf_headers,
        )
        assert resp.status_code == 201
    over_resp = await client.post(
        "/api/v1/channels",
        json={"kind": "email", "name": "over", "config": {"address": "over@example.com"}},
        headers=csrf_headers,
    )
    assert over_resp.status_code == 422
    assert over_resp.json()["error"]["code"] == "plan_limit"


async def test_patching_the_address_resets_verification(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)
    create_resp = await client.post("/api/v1/channels", json=_EMAIL_PAYLOAD, headers=csrf_headers)
    channel_id = create_resp.json()["id"]

    await db_session.execute(
        update(NotificationChannel)
        .where(NotificationChannel.id == uuid.UUID(channel_id))
        .values(verified_at=text("now()"))
    )
    await db_session.commit()

    patch_resp = await client.patch(
        f"/api/v1/channels/{channel_id}",
        json={"config": {"address": "new-address@example.com"}},
        headers=csrf_headers,
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["verified_at"] is None


async def test_cross_account_channel_is_404(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)
    create_resp = await client.post("/api/v1/channels", json=_EMAIL_PAYLOAD, headers=csrf_headers)
    channel_id = create_resp.json()["id"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as other:
        await login_as(other, db_session, app.state.clock)
        resp = await other.get(f"/api/v1/channels/{channel_id}")
        assert resp.status_code == 404
        other_csrf = await other.get("/api/v1/auth/csrf")
        assert other_csrf.status_code == 200
        headers = {"X-CSRF-Token": other.cookies.get("cronos_csrf")}
        delete_resp = await other.delete(f"/api/v1/channels/{channel_id}", headers=headers)
        assert delete_resp.status_code == 404


# ---- Email verification ----


async def test_own_verified_account_address_verifies_immediately(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    user = await login_as(client, db_session, app.state.clock)
    resp = await client.post(
        "/api/v1/channels",
        json={"kind": "email", "name": "me", "config": {"address": user.email}},
        headers=csrf_headers,
    )
    channel_id = resp.json()["id"]

    verify_resp = await client.post(f"/api/v1/channels/{channel_id}/verify", headers=csrf_headers)
    assert verify_resp.status_code == 200
    assert verify_resp.json()["verified_at"] is not None


async def test_a_different_address_requires_the_token_link(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)
    create_resp = await client.post("/api/v1/channels", json=_EMAIL_PAYLOAD, headers=csrf_headers)
    channel_id = create_resp.json()["id"]

    verify_resp = await client.post(f"/api/v1/channels/{channel_id}/verify", headers=csrf_headers)
    assert verify_resp.status_code == 200
    assert verify_resp.json()["verified_at"] is None  # a link was sent, not immediately verified

    row = (
        await db_session.execute(
            select(NotificationChannel).where(NotificationChannel.id == uuid.UUID(channel_id))
        )
    ).scalar_one()
    assert row.verify_token_hash is not None


async def test_invalid_verify_email_token_is_rejected(
    client: AsyncClient, db_session: AsyncSession, app: FastAPI
) -> None:
    resp = await client.post("/api/v1/channels/verify-email", json={"token": "garbage"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_token"


# ---- Webhook verification / test-send ----


async def test_webhook_verify_succeeds_on_2xx(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI, chaos_control
) -> None:
    await chaos_control(status_code=200)
    await login_as(client, db_session, app.state.clock)
    create_resp = await client.post(
        "/api/v1/channels", json=_webhook_payload(), headers=csrf_headers
    )
    channel_id = create_resp.json()["id"]

    verify_resp = await client.post(f"/api/v1/channels/{channel_id}/verify", headers=csrf_headers)
    assert verify_resp.status_code == 200
    assert verify_resp.json()["verified_at"] is not None


async def test_webhook_verify_fails_on_non_2xx(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI, chaos_control
) -> None:
    await chaos_control(status_code=500)
    await login_as(client, db_session, app.state.clock)
    create_resp = await client.post(
        "/api/v1/channels", json=_webhook_payload(), headers=csrf_headers
    )
    channel_id = create_resp.json()["id"]

    verify_resp = await client.post(f"/api/v1/channels/{channel_id}/verify", headers=csrf_headers)
    assert verify_resp.status_code == 422
    assert verify_resp.json()["error"]["code"] == "webhook_verify_failed"


async def test_webhook_verify_signature_matches_the_revealed_secret(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI, chaos_control, chaos_log
) -> None:
    await chaos_control(status_code=200)
    await login_as(client, db_session, app.state.clock)
    create_resp = await client.post(
        "/api/v1/channels", json=_webhook_payload(), headers=csrf_headers
    )
    channel_id = create_resp.json()["id"]

    secret_resp = await client.get(f"/api/v1/channels/{channel_id}/secret")
    assert secret_resp.status_code == 200
    secret = secret_resp.json()["secret"]
    await chaos_control(status_code=200, webhook_secret=secret)

    before_log = await chaos_log()
    verify_resp = await client.post(f"/api/v1/channels/{channel_id}/verify", headers=csrf_headers)
    assert verify_resp.status_code == 200

    after_log = await chaos_log()
    new_rows = after_log[len(before_log):]
    assert any(row["verified"] is True for row in new_rows)


async def test_test_send_requires_verification_first(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)
    create_resp = await client.post("/api/v1/channels", json=_EMAIL_PAYLOAD, headers=csrf_headers)
    channel_id = create_resp.json()["id"]

    resp = await client.post(f"/api/v1/channels/{channel_id}/test", headers=csrf_headers)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "channel_unverified"


# ---- Secret reveal / rotate ----


async def test_rotate_secret_returns_a_new_plaintext_value(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)
    create_resp = await client.post(
        "/api/v1/channels", json=_webhook_payload("http://chaos:8000/webhook"), headers=csrf_headers
    )
    channel_id = create_resp.json()["id"]

    first_reveal = await client.get(f"/api/v1/channels/{channel_id}/secret")
    rotate_resp = await client.post(f"/api/v1/channels/{channel_id}/rotate-secret", headers=csrf_headers)
    assert rotate_resp.status_code == 200
    second_reveal = await client.get(f"/api/v1/channels/{channel_id}/secret")

    assert first_reveal.json()["secret"] != rotate_resp.json()["secret"]
    assert second_reveal.json()["secret"] == rotate_resp.json()["secret"]


async def test_reveal_and_rotate_require_a_session_not_an_api_key(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    user = await login_as(client, db_session, app.state.clock)
    create_resp = await client.post(
        "/api/v1/channels", json=_webhook_payload("http://chaos:8000/webhook"), headers=csrf_headers
    )
    channel_id = create_resp.json()["id"]

    full_key, prefix, key_hash = generate_api_key()
    await make_api_key(
        db_session, user.account_id, prefix=prefix, key_hash=key_hash,
        scopes=["channels:read", "channels:write"], created_by_user_id=user.id,
    )
    await db_session.commit()
    headers = {"Authorization": f"Bearer {full_key}"}

    reveal_resp = await client.get(f"/api/v1/channels/{channel_id}/secret", headers=headers)
    assert reveal_resp.status_code == 403
    assert reveal_resp.json()["error"]["code"] == "session_required"

    rotate_resp = await client.post(f"/api/v1/channels/{channel_id}/rotate-secret", headers=headers)
    assert rotate_resp.status_code == 403
    assert rotate_resp.json()["error"]["code"] == "session_required"


# ---- Deliveries ----


async def test_deliveries_lists_notifications_for_the_channel(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    user = await login_as(client, db_session, app.state.clock)
    channel = await make_notification_channel(db_session, user.account_id)
    await make_notification(db_session, user.account_id, channel.id, status="sent")
    await db_session.commit()

    resp = await client.get(f"/api/v1/channels/{channel.id}/deliveries")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["status"] == "sent"


# ---- Routing ----


async def test_monitor_channel_routing_replaces_the_full_set(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)
    monitor_resp = await client.post(
        "/api/v1/monitors", json={"name": "r", "url": "http://chaos:8000/health"}, headers=csrf_headers
    )
    monitor_id = monitor_resp.json()["id"]

    c1 = (await client.post("/api/v1/channels", json=_EMAIL_PAYLOAD, headers=csrf_headers)).json()
    c2 = (
        await client.post(
            "/api/v1/channels",
            json={"kind": "email", "name": "second", "config": {"address": "second@example.com"}},
            headers=csrf_headers,
        )
    ).json()

    put_resp = await client.put(
        f"/api/v1/monitors/{monitor_id}/channels", json={"channel_ids": [c1["id"]]}, headers=csrf_headers
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["channel_ids"] == [c1["id"]]

    replace_resp = await client.put(
        f"/api/v1/monitors/{monitor_id}/channels", json={"channel_ids": [c2["id"]]}, headers=csrf_headers
    )
    assert replace_resp.status_code == 200
    assert replace_resp.json()["channel_ids"] == [c2["id"]]

    get_resp = await client.get(f"/api/v1/monitors/{monitor_id}/channels")
    assert get_resp.json()["channel_ids"] == [c2["id"]]


async def test_routing_a_foreign_channel_id_404s_the_whole_request(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    await login_as(client, db_session, app.state.clock)
    monitor_resp = await client.post(
        "/api/v1/monitors", json={"name": "r", "url": "http://chaos:8000/health"}, headers=csrf_headers
    )
    monitor_id = monitor_resp.json()["id"]
    own_channel = (await client.post("/api/v1/channels", json=_EMAIL_PAYLOAD, headers=csrf_headers)).json()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as other:
        await login_as(other, db_session, app.state.clock)
        other_csrf = await other.get("/api/v1/auth/csrf")
        other_headers = {"X-CSRF-Token": other.cookies.get("cronos_csrf")}
        foreign_channel = (
            await other.post("/api/v1/channels", json=_EMAIL_PAYLOAD, headers=other_headers)
        ).json()

    resp = await client.put(
        f"/api/v1/monitors/{monitor_id}/channels",
        json={"channel_ids": [own_channel["id"], foreign_channel["id"]]},
        headers=csrf_headers,
    )
    assert resp.status_code == 404

    # The whole request was rejected -- the owned channel was NOT partially applied either.
    get_resp = await client.get(f"/api/v1/monitors/{monitor_id}/channels")
    assert get_resp.json()["channel_ids"] == []
