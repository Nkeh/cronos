"""Webhook delivery. Reuses app/engine/guarded_backend.py's GuardedBackend verbatim (SSRF at
connect time) and mirrors app/engine/http_probe.py's HttpProbe.check transport-wiring internals,
with the differences SRS Section 13 requires for webhooks specifically: follow_redirects=False /
max_redirects=0 (monitors get up to 3; webhooks get none), a POST with a signed JSON body instead
of GET/HEAD, a fixed 5s timeout instead of a per-monitor value, and a 4KB body cap instead of 64KB.

The wire payload (SRS Section 10) is built fresh here from DeliveryContext, not read from the
stored Notification.payload -- app/engine/state.py's stored payload is a small internal shape;
only this module needs to know the external wire contract.

_post_signed is the one function that actually opens a connection; both a real delivery
(deliver_webhook) and a channel's verify/test send (send_signed_event, used synchronously from
app/notifications/router.py -- a sanctioned CLAUDE.md exception, same bucket as the email-verify-
link BackgroundTask) go through it, so the SSRF guard and the signature scheme are exercised
identically either way.
"""

from __future__ import annotations

import asyncio
import json
import ssl
import time
import uuid
from urllib.parse import urlsplit

import certifi
import httpcore
import httpx
import structlog

from app.core.config import Settings
from app.core.crypto import decrypt_secret
from app.engine.guarded_backend import BlockedAddressError, ConnectTimings, DnsResolutionError, GuardedBackend
from app.notifications.cause_copy import cause_copy
from app.notifier.delivery import DeliveryContext
from app.notifier.outcomes import DeliveryOutcome
from app.notifier.signing import sign

logger = structlog.get_logger()

_MAX_ERROR_LENGTH = 500
_WEBHOOK_MAX_REDIRECTS = 0  # SRS Section 13 -- fixed, never a Settings field (see module docstring).


def _redact_url(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def _build_wire_payload(ctx: DeliveryContext) -> dict:
    """SRS Section 10's {id, event, occurred_at, incident{...}, monitor{...}} shape."""
    body: dict = {
        "id": str(ctx.notification_id),
        "event": ctx.event,
        "occurred_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if ctx.incident_id is not None:
        body["incident"] = {
            "id": str(ctx.incident_id),
            "cause": ctx.incident_cause,
            "cause_label": cause_copy(ctx.incident_cause),
            "started_at": ctx.incident_started_at.isoformat() if ctx.incident_started_at else None,
            "confirmed_at": ctx.incident_confirmed_at.isoformat() if ctx.incident_confirmed_at else None,
            "resolved_at": ctx.incident_resolved_at.isoformat() if ctx.incident_resolved_at else None,
            "resolved_reason": ctx.incident_resolved_reason,
            "duration_seconds": ctx.incident_duration_seconds,
            "last_error": ctx.incident_last_error,
        }
        body["monitor"] = {
            "id": str(ctx.monitor_id) if ctx.monitor_id else None,
            "name": ctx.subject_name,
            "url": ctx.monitor_url,
        }
    elif ctx.event == "flapping":
        body["subject"] = {
            "id": str(ctx.monitor_id) if ctx.monitor_id else None,
            "name": ctx.subject_name,
            "phase": ctx.flap_phase,
        }
    elif ctx.event == "cap_reached":
        body["cap"] = {"kind": ctx.cap_kind}
    return body


async def _post_signed(
    settings: Settings, *, url: str, secret: bytes, event: str, delivery_id: str, body: bytes
) -> DeliveryOutcome:
    timestamp = int(time.time())
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Cronos-Webhook/1.0",
        "X-Cronos-Event": event,
        "X-Cronos-Delivery": delivery_id,
        "X-Cronos-Timestamp": str(timestamp),
        "X-Cronos-Signature": sign(secret, timestamp, body),
    }

    timings = ConnectTimings()
    backend = GuardedBackend(timings=timings, allow_hosts=settings.ssrf_allow_hosts_set)
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    transport = httpx.AsyncHTTPTransport(trust_env=False, retries=0)
    # Same private-attribute seam as HttpProbe.check (app/engine/http_probe.py) -- see its
    # comment; tests/notifier/test_webhook.py mirrors test_http_probe_seam.py's canary test.
    transport._pool = httpcore.AsyncConnectionPool(
        ssl_context=ssl_context, network_backend=backend, max_connections=1,
        max_keepalive_connections=0, retries=0,
    )

    try:
        async with httpx.AsyncClient(
            transport=transport, trust_env=False,
            timeout=httpx.Timeout(settings.webhook_timeout_seconds),
            follow_redirects=False, max_redirects=_WEBHOOK_MAX_REDIRECTS,
        ) as client:
            async with asyncio.timeout(settings.webhook_timeout_seconds):
                request = client.build_request("POST", url, content=body, headers=headers)
                response = await client.send(request, stream=True)
                read = 0
                async for chunk in response.aiter_bytes():
                    read += len(chunk)
                    if read >= settings.webhook_body_cap_bytes:
                        break
                await response.aclose()
    except BlockedAddressError:
        return DeliveryOutcome(outcome="failed", error="blocked by SSRF policy")
    except DnsResolutionError:
        return DeliveryOutcome(outcome="failed", error="DNS resolution failed")
    except (TimeoutError, httpx.TimeoutException):
        return DeliveryOutcome(outcome="retry", error="timed out")
    except (
        httpx.ConnectError, httpx.NetworkError, httpx.ProtocolError,
        httpx.RemoteProtocolError, httpx.LocalProtocolError,
    ) as exc:
        return DeliveryOutcome(outcome="retry", error=str(exc)[:_MAX_ERROR_LENGTH])
    except Exception as exc:  # noqa: BLE001 - one bad delivery must never crash the caller
        logger.warning(
            "webhook_delivery_unclassified_error", url=_redact_url(url), error=str(exc)[:_MAX_ERROR_LENGTH]
        )
        return DeliveryOutcome(outcome="failed", error=str(exc)[:_MAX_ERROR_LENGTH])

    status = response.status_code
    if status in (408, 429) or status >= 500:
        retry_after: int | None = None
        if status == 429:
            header = response.headers.get("Retry-After")
            if header is not None:
                try:
                    retry_after = min(int(header), 3600)
                except ValueError:
                    pass
        return DeliveryOutcome(outcome="retry", status_code=status, retry_after_seconds=retry_after)
    if 200 <= status < 300:
        return DeliveryOutcome(outcome="sent", status_code=status)
    # 3xx (a redirect was attempted -- never followed) or any other 4xx: a config error on the
    # receiving end, not a transient one.
    return DeliveryOutcome(outcome="failed", status_code=status, error=f"unexpected status {status}")


async def deliver_webhook(settings: Settings, ctx: DeliveryContext) -> DeliveryOutcome:
    if not ctx.channel_secret:
        return DeliveryOutcome(outcome="failed", error="webhook channel has no secret")
    secret = decrypt_secret(ctx.channel_secret, settings.encryption_key)
    url = ctx.channel_config.get("url")
    if not url:
        return DeliveryOutcome(outcome="failed", error="webhook channel has no url")

    body = json.dumps(_build_wire_payload(ctx)).encode("utf-8")
    return await _post_signed(
        settings, url=url, secret=secret, event=ctx.event,
        delivery_id=str(ctx.notification_id), body=body,
    )


async def send_test_event(
    settings: Settings, *, url: str, secret: bytes, event: str = "test"
) -> DeliveryOutcome:
    """Used synchronously by the Channels API: webhook verification (one signed 'test' POST,
    2xx required to verify) and the "send test" button (verified channels only). Not part of the
    outbox -- no Notification row, no retry, no notification_attempts entry; the caller gets the
    DeliveryOutcome directly and decides what to do with it."""
    body = json.dumps(
        {"id": str(uuid.uuid4()), "event": event, "occurred_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    ).encode("utf-8")
    return await _post_signed(
        settings, url=url, secret=secret, event=event, delivery_id=str(uuid.uuid4()), body=body
    )
