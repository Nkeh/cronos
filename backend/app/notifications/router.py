"""Channels API: /api/v1/channels. Tenant isolation copied verbatim from app/monitors/router.py's
_get_owned_channel pattern (cross-account lookups always 404, never 403) -- same established
per-router convention as incidents/router.py.

Two sanctioned CLAUDE.md outbox exceptions live here, alongside Day 3's auth emails:
- Channel email verification sends its link via BackgroundTasks, not the outbox (account-setup
  plumbing, not an alert -- a lost verification email is recoverable via resend).
- Webhook verification (and the "send test" button) sends one signed event synchronously,
  through the same guarded transport real deliveries use, so a 2xx really proves the receiver
  works -- also not the outbox: there is no Notification row, no retry, nothing to drain.

Secret handling: POST never returns a webhook's secret (unlike API keys' shown-once pattern --
a webhook secret legitimately needs to be re-pasted into a receiver's config later, so reveal is
its own rate-limited, session-only endpoint instead). PATCHing config.address/config.url resets
verification; the channel stops being routed to until re-verified (enforced by
enqueue_notifications's existing verified_at filter, unchanged since Day 8).
"""

from __future__ import annotations

import base64
import re
import secrets
import uuid
from datetime import datetime

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import select, text, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    AuthContext,
    require_scope,
    require_verified,
    require_verified_session_user,
)
from app.auth.models import User
from app.auth.rate_limit import enforce_rate_limit
from app.auth.security import hash_token, new_raw_token
from app.core.config import Settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.db import get_db_session
from app.core.dependencies import get_email_sender, get_redis, get_settings_dep
from app.core.email import EmailSender, render_channel_test_email, render_verify_email
from app.core.errors import ApiError
from app.core.redis import FailOpenRedis
from app.engine import ssrf_policy
from app.notifications.models import Notification, NotificationAttempt, NotificationChannel
from app.notifications.schemas import (
    ChannelCreate,
    ChannelPatch,
    ChannelPublic,
    ChannelSecretResponse,
    ChannelTestResponse,
    ChannelVerifyEmailRequest,
    DeliveryAttemptPublic,
    DeliveryListResponse,
    DeliveryPublic,
)
from app.notifier.webhook import send_test_event
from app.plans.dependencies import check_limit, get_account_for_update

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/channels", tags=["channels"])

_MAX_LIMIT = 100
_EMAIL_PATTERN_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_webhook_url(raw_url: str, settings: Settings) -> ssrf_policy.ParsedUrl:
    """Duplicated from monitors/router.py's _validate_url (not imported): a deliberate 12-line
    tradeoff over widening app/engine/ssrf_policy.py's "pure functions, no DB access, no
    ApiError" contract just to share two wrapper functions. See docs/progress/day-09.md."""
    try:
        return ssrf_policy.normalize_and_validate_url(raw_url, allow_hosts=settings.ssrf_allow_hosts_set)
    except ssrf_policy.UrlPolicyError as exc:
        raise ApiError(422, exc.code, exc.message, field="config.url") from None


async def _validate_webhook_url_resolves(parsed: ssrf_policy.ParsedUrl, settings: Settings) -> None:
    try:
        await ssrf_policy.check_dns_resolves_public(parsed.host, allow_hosts=settings.ssrf_allow_hosts_set)
    except ssrf_policy.UrlPolicyError as exc:
        raise ApiError(422, exc.code, exc.message, field="config.url") from None


def _validate_email_config(config: dict) -> dict:
    address = config.get("address")
    if not isinstance(address, str) or not _EMAIL_PATTERN_RE.match(address):
        raise ApiError(422, "validation_error", "A valid email address is required.", field="config.address")
    return {"address": address}


async def _validate_webhook_config(config: dict, settings: Settings) -> dict:
    url = config.get("url")
    if not isinstance(url, str) or not url:
        raise ApiError(422, "validation_error", "A webhook URL is required.", field="config.url")
    parsed = _validate_webhook_url(url, settings)
    await _validate_webhook_url_resolves(parsed, settings)
    return {"url": parsed.normalized_url}


async def _get_owned_channel(
    db: AsyncSession, account_id: uuid.UUID, channel_id: uuid.UUID
) -> NotificationChannel:
    channel = (
        await db.execute(
            select(NotificationChannel).where(
                NotificationChannel.account_id == account_id, NotificationChannel.id == channel_id
            )
        )
    ).scalar_one_or_none()
    if channel is None:
        raise ApiError(404, "not_found", "Channel not found.")
    return channel


def _encode_cursor(created_at: datetime, notification_id: uuid.UUID) -> str:
    raw = f"{created_at.isoformat()}|{notification_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        created_at_str, id_str = raw.split("|", 1)
        return datetime.fromisoformat(created_at_str), uuid.UUID(id_str)
    except Exception:
        raise ApiError(422, "invalid_cursor", "Malformed cursor.", field="cursor") from None


@router.get("", response_model=list[ChannelPublic])
async def list_channels(
    principal: AuthContext = Depends(require_scope("channels:read")),
    db: AsyncSession = Depends(get_db_session),
) -> list[ChannelPublic]:
    rows = (
        (
            await db.execute(
                select(NotificationChannel)
                .where(NotificationChannel.account_id == principal.user.account_id)
                .order_by(NotificationChannel.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [ChannelPublic.model_validate(row) for row in rows]


@router.post("", response_model=ChannelPublic, status_code=201)
async def create_channel(
    payload: ChannelCreate,
    user: User = Depends(require_verified),
    _scope: AuthContext = Depends(require_scope("channels:write")),
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings_dep),
) -> ChannelPublic:
    # --- validation phase: no lock held yet ---
    if payload.kind == "email":
        config = _validate_email_config(payload.config)
    else:
        config = await _validate_webhook_config(payload.config, settings)

    # --- short final block: lock -> count -> insert -> commit, DB-only awaits ---
    account = await get_account_for_update(db, user.account_id)
    await check_limit(db, account, "channels")

    secret: bytes | None = None
    if payload.kind == "webhook":
        raw_secret = secrets.token_urlsafe(32)
        secret = encrypt_secret(raw_secret.encode("utf-8"), settings.encryption_key)

    channel = NotificationChannel(
        account_id=account.id,
        kind=payload.kind,
        name=payload.name,
        config=config,
        secret=secret,
        is_default=payload.is_default,
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)

    logger.info("channel_created", channel_id=str(channel.id), account_id=str(account.id), kind=payload.kind)
    return ChannelPublic.model_validate(channel)


@router.patch("/{channel_id}", response_model=ChannelPublic)
async def patch_channel(
    channel_id: uuid.UUID,
    payload: ChannelPatch,
    user: User = Depends(require_verified),
    _scope: AuthContext = Depends(require_scope("channels:write")),
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings_dep),
) -> ChannelPublic:
    channel = await _get_owned_channel(db, user.account_id, channel_id)
    data = payload.model_dump(exclude_unset=True)

    config_changed = False
    if "config" in data and data["config"] is not None:
        if channel.kind == "email":
            new_config = _validate_email_config(data["config"])
        else:
            new_config = await _validate_webhook_config(data["config"], settings)
        config_changed = new_config != channel.config
        channel.config = new_config
        del data["config"]

    for field_name, value in data.items():
        setattr(channel, field_name, value)

    if config_changed:
        channel.verified_at = None
        channel.verify_token_hash = None
        channel.verify_expires_at = None

    await db.commit()
    await db.refresh(channel)
    logger.info("channel_patched", channel_id=str(channel.id), fields=sorted(data))
    return ChannelPublic.model_validate(channel)


@router.delete("/{channel_id}", status_code=204)
async def delete_channel(
    channel_id: uuid.UUID,
    user: User = Depends(require_verified),
    _scope: AuthContext = Depends(require_scope("channels:write")),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    channel = await _get_owned_channel(db, user.account_id, channel_id)
    await db.delete(channel)
    await db.commit()
    logger.info("channel_deleted", channel_id=str(channel_id), account_id=str(user.account_id))


@router.post("/{channel_id}/verify", response_model=ChannelPublic)
async def verify_channel(
    channel_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_verified),
    _scope: AuthContext = Depends(require_scope("channels:write")),
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings_dep),
    redis: FailOpenRedis = Depends(get_redis),
    email_sender: EmailSender = Depends(get_email_sender),
) -> ChannelPublic:
    channel = await _get_owned_channel(db, user.account_id, channel_id)
    await enforce_rate_limit(
        redis,
        key=f"ratelimit:channel-verify:{channel_id}",
        max_requests=settings.channel_verify_rate_limit_max,
        window_seconds=settings.channel_verify_rate_limit_window_seconds,
    )

    if channel.kind == "email":
        address = channel.config.get("address")
        if address == user.email and user.email_verified_at is not None:
            await db.execute(
                update(NotificationChannel)
                .where(NotificationChannel.id == channel.id)
                .values(verified_at=text("now()"))
            )
            await db.commit()
            await db.refresh(channel)
            return ChannelPublic.model_validate(channel)

        raw_token = new_raw_token()
        await db.execute(
            update(NotificationChannel)
            .where(NotificationChannel.id == channel.id)
            .values(
                verify_token_hash=hash_token(raw_token),
                verify_expires_at=text("now() + make_interval(hours => :ttl)").bindparams(
                    ttl=settings.channel_verify_token_ttl_hours
                ),
            )
        )
        await db.commit()
        await db.refresh(channel)

        link = f"{settings.public_origin}/channels/verify?token={raw_token}"
        background_tasks.add_task(email_sender.send, render_verify_email(to=address, link=link))
        return ChannelPublic.model_validate(channel)

    # webhook: one signed 'test' POST, synchronous, 2xx required.
    if not channel.secret:
        raise ApiError(500, "internal_error", "Webhook channel has no secret.")
    secret = decrypt_secret(channel.secret, settings.encryption_key)
    url = channel.config.get("url")
    outcome = await send_test_event(settings, url=url, secret=secret, event="test")
    if outcome.outcome != "sent":
        raise ApiError(
            422, "webhook_verify_failed",
            outcome.error or f"Webhook responded with status {outcome.status_code}.",
        )
    await db.execute(
        update(NotificationChannel).where(NotificationChannel.id == channel.id).values(verified_at=text("now()"))
    )
    await db.commit()
    await db.refresh(channel)
    return ChannelPublic.model_validate(channel)


@router.post("/verify-email", response_model=dict)
async def verify_channel_email(
    payload: ChannelVerifyEmailRequest, db: AsyncSession = Depends(get_db_session)
) -> dict:
    token_hash = hash_token(payload.token)
    channel = (
        await db.execute(
            select(NotificationChannel).where(
                NotificationChannel.verify_token_hash == token_hash,
                NotificationChannel.verify_expires_at > text("now()"),
            )
        )
    ).scalar_one_or_none()
    if channel is None:
        # One generic code for bad/expired/wrong -- same reasoning as app/auth/router.py's verify().
        raise ApiError(400, "invalid_token", "Invalid or expired token.")

    await db.execute(
        update(NotificationChannel)
        .where(NotificationChannel.id == channel.id)
        .values(verified_at=text("now()"), verify_token_hash=None, verify_expires_at=None)
    )
    await db.commit()
    logger.info("channel_email_verified", channel_id=str(channel.id))
    return {"message": "Channel verified."}


@router.post("/{channel_id}/test", response_model=ChannelTestResponse)
async def test_channel(
    channel_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_verified),
    _scope: AuthContext = Depends(require_scope("channels:write")),
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings_dep),
    redis: FailOpenRedis = Depends(get_redis),
    email_sender: EmailSender = Depends(get_email_sender),
) -> ChannelTestResponse:
    channel = await _get_owned_channel(db, user.account_id, channel_id)
    if channel.verified_at is None:
        raise ApiError(409, "channel_unverified", "Verify this channel before sending a test.")
    await enforce_rate_limit(
        redis,
        key=f"ratelimit:channel-verify:{channel_id}",
        max_requests=settings.channel_verify_rate_limit_max,
        window_seconds=settings.channel_verify_rate_limit_window_seconds,
    )

    if channel.kind == "email":
        address = channel.config.get("address")
        background_tasks.add_task(email_sender.send, render_channel_test_email(to=address))
        return ChannelTestResponse(ok=True)

    if not channel.secret:
        raise ApiError(500, "internal_error", "Webhook channel has no secret.")
    secret = decrypt_secret(channel.secret, settings.encryption_key)
    url = channel.config.get("url")
    outcome = await send_test_event(settings, url=url, secret=secret, event="test")
    return ChannelTestResponse(ok=outcome.outcome == "sent", status_code=outcome.status_code, error=outcome.error)


@router.post("/{channel_id}/rotate-secret", response_model=ChannelSecretResponse)
async def rotate_secret(
    channel_id: uuid.UUID,
    user: User = Depends(require_verified_session_user),
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings_dep),
) -> ChannelSecretResponse:
    channel = await _get_owned_channel(db, user.account_id, channel_id)
    if channel.kind != "webhook":
        raise ApiError(422, "validation_error", "Only webhook channels have a secret.")

    raw_secret = secrets.token_urlsafe(32)
    channel.secret = encrypt_secret(raw_secret.encode("utf-8"), settings.encryption_key)
    await db.commit()
    logger.info("channel_secret_rotated", channel_id=str(channel.id))
    return ChannelSecretResponse(secret=raw_secret)


@router.get("/{channel_id}/secret", response_model=ChannelSecretResponse)
async def reveal_secret(
    channel_id: uuid.UUID,
    user: User = Depends(require_verified_session_user),
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings_dep),
    redis: FailOpenRedis = Depends(get_redis),
) -> ChannelSecretResponse:
    channel = await _get_owned_channel(db, user.account_id, channel_id)
    if channel.kind != "webhook" or not channel.secret:
        raise ApiError(422, "validation_error", "Only webhook channels have a secret.")
    await enforce_rate_limit(
        redis,
        key=f"ratelimit:channel-secret-reveal:{channel_id}",
        max_requests=settings.channel_verify_rate_limit_max,
        window_seconds=settings.channel_verify_rate_limit_window_seconds,
    )
    raw_secret = decrypt_secret(channel.secret, settings.encryption_key).decode("utf-8")
    return ChannelSecretResponse(secret=raw_secret)


@router.get("/{channel_id}/deliveries", response_model=DeliveryListResponse)
async def list_deliveries(
    channel_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = Query(default=25, ge=1, le=_MAX_LIMIT),
    principal: AuthContext = Depends(require_scope("channels:read")),
    db: AsyncSession = Depends(get_db_session),
) -> DeliveryListResponse:
    await _get_owned_channel(db, principal.user.account_id, channel_id)

    conditions = [Notification.channel_id == channel_id]
    if cursor is not None:
        cursor_created_at, cursor_id = _decode_cursor(cursor)
        conditions.append(
            tuple_(Notification.created_at, Notification.id) < tuple_(cursor_created_at, cursor_id)
        )

    rows = (
        (
            await db.execute(
                select(Notification)
                .where(*conditions)
                .order_by(Notification.created_at.desc(), Notification.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    items: list[DeliveryPublic] = []
    for row in rows:
        attempts = (
            (
                await db.execute(
                    select(NotificationAttempt)
                    .where(NotificationAttempt.notification_id == row.id)
                    .order_by(NotificationAttempt.attempted_at.desc())
                )
            )
            .scalars()
            .all()
        )
        items.append(
            DeliveryPublic(
                id=row.id, event=row.event, status=row.status, attempts=row.attempts,
                created_at=row.created_at, sent_at=row.sent_at, last_error=row.last_error,
                recent_attempts=[DeliveryAttemptPublic.model_validate(a) for a in attempts],
            )
        )

    next_cursor = _encode_cursor(rows[-1].created_at, rows[-1].id) if len(rows) == limit else None
    return DeliveryListResponse(items=items, next_cursor=next_cursor)
