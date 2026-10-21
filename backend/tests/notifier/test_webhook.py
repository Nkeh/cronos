"""Integration tests against the LIVE chaos container (reachable as host "chaos" on the Compose
default network) -- same convention as tests/engine/test_http_probe_chaos.py. Drives
deliver_webhook/_post_signed against chaos's real /webhook endpoint (Day 9's real HMAC
verification) to prove the SSRF guard, signing, and outcome classification end to end.

chaos's /webhook route is a single fixed path (not a wildcard like its GET/HEAD target routes),
so every test here shares that one path/control entry -- POST /_control resets its response-
sequence cursor on every call, and every log assertion filters by this delivery's own
notification id, so tests stay independent despite the shared path.
"""

from __future__ import annotations

import uuid

import httpx
import pytest_asyncio

from app.core.config import get_settings
from app.core.crypto import encrypt_secret
from app.notifier.delivery import DeliveryContext
from app.notifier.webhook import deliver_webhook, send_test_event

_WEBHOOK_URL = "http://chaos:8000/webhook"


def _settings():
    return get_settings().model_copy(update={"ssrf_allow_hosts": "chaos"})


def _ctx(*, secret: bytes, event: str = "opened", url: str = _WEBHOOK_URL, **overrides) -> DeliveryContext:
    defaults = dict(
        notification_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        event=event,
        payload={},
        attempts=1,
        channel_id=uuid.uuid4(),
        channel_kind="webhook",
        channel_config={"url": url},
        channel_secret=secret,
        subject_name="api",
        incident_id=uuid.uuid4(),
        incident_cause="http_status",
    )
    defaults.update(overrides)
    return DeliveryContext(**defaults)


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


async def test_successful_delivery_is_verified_on_the_receiving_end(chaos_control, chaos_log) -> None:
    await chaos_control(status_code=200, webhook_secret="s3cret")
    secret = encrypt_secret(b"s3cret", get_settings().encryption_key)

    ctx = _ctx(secret=secret)
    outcome = await deliver_webhook(_settings(), ctx)

    assert outcome.outcome == "sent"
    assert outcome.status_code == 200

    log = await chaos_log()
    delivered = [row for row in log if row["delivery_id"] == str(ctx.notification_id)]
    assert len(delivered) == 1
    assert delivered[0]["verified"] is True
    assert delivered[0]["event"] == "opened"


async def test_wrong_secret_fails_verification_on_the_receiving_end(chaos_control, chaos_log) -> None:
    await chaos_control(status_code=200, webhook_secret="the-real-secret")
    wrong_secret = encrypt_secret(b"not-the-real-secret", get_settings().encryption_key)

    ctx = _ctx(secret=wrong_secret)
    outcome = await deliver_webhook(_settings(), ctx)
    assert outcome.outcome == "sent"  # chaos still returns 200 -- it logs verified=False, doesn't reject

    log = await chaos_log()
    delivered = [row for row in log if row["delivery_id"] == str(ctx.notification_id)]
    assert delivered[0]["verified"] is False


async def test_500_then_200_sequence_is_retried_then_delivered(chaos_control) -> None:
    await chaos_control(response_sequence=[500, 500, 200], webhook_secret="s")
    secret = encrypt_secret(b"s", get_settings().encryption_key)
    ctx = _ctx(secret=secret)

    first = await deliver_webhook(_settings(), ctx)
    second = await deliver_webhook(_settings(), ctx)
    third = await deliver_webhook(_settings(), ctx)

    assert (first.outcome, first.status_code) == ("retry", 500)
    assert (second.outcome, second.status_code) == ("retry", 500)
    assert (third.outcome, third.status_code) == ("sent", 200)


async def test_404_is_a_permanent_failure(chaos_control) -> None:
    await chaos_control(status_code=404, webhook_secret="s")
    secret = encrypt_secret(b"s", get_settings().encryption_key)
    ctx = _ctx(secret=secret)

    outcome = await deliver_webhook(_settings(), ctx)
    assert outcome.outcome == "failed"
    assert outcome.status_code == 404


async def test_429_is_a_retry(chaos_control) -> None:
    # chaos has no way to set a Retry-After header -- the "capped at 3600s, honoured when
    # present" behavior is covered directly (no live chaos needed) in tests/notifier/test_record.py.
    await chaos_control(status_code=429, webhook_secret="s")
    secret = encrypt_secret(b"s", get_settings().encryption_key)
    ctx = _ctx(secret=secret)

    outcome = await deliver_webhook(_settings(), ctx)
    assert outcome.outcome == "retry"
    assert outcome.status_code == 429


async def test_a_3xx_response_is_never_followed_and_is_a_permanent_failure(chaos_control) -> None:
    # chaos's receive_webhook doesn't implement a redirect Location header (only its GET/HEAD
    # target routes do) -- a bare 3xx status with no Location is enough to prove the sender
    # classifies it as a permanent failure rather than trying to follow anything.
    await chaos_control(status_code=302, webhook_secret="s")
    secret = encrypt_secret(b"s", get_settings().encryption_key)
    ctx = _ctx(secret=secret)

    outcome = await deliver_webhook(_settings(), ctx)
    assert outcome.outcome == "failed"
    assert outcome.status_code == 302


async def test_blocked_private_address_fails_without_sending() -> None:
    secret = encrypt_secret(b"s", get_settings().encryption_key)
    ctx = _ctx(secret=secret, url="http://169.254.169.254/latest/meta-data/")

    outcome = await deliver_webhook(get_settings(), ctx)  # no ssrf_allow_hosts override here
    assert outcome.outcome == "failed"
    assert "blocked" in (outcome.error or "").lower()


async def test_signature_header_matches_the_shared_signing_scheme(chaos_control, chaos_log) -> None:
    await chaos_control(status_code=200, webhook_secret="verify-me")
    secret = encrypt_secret(b"verify-me", get_settings().encryption_key)
    ctx = _ctx(secret=secret, event="resolved")

    await deliver_webhook(_settings(), ctx)

    log = await chaos_log()
    delivered = [row for row in log if row["delivery_id"] == str(ctx.notification_id)]
    assert delivered[0]["verified"] is True
    assert delivered[0]["signature_header"].startswith("v1=")


async def test_send_test_event_round_trips_through_the_same_transport(chaos_control) -> None:
    await chaos_control(status_code=200, webhook_secret="s")
    outcome = await send_test_event(_settings(), url=_WEBHOOK_URL, secret=b"s")
    assert outcome.outcome == "sent"
