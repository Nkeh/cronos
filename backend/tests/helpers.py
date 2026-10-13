"""Plain functions for building valid rows in constraint tests.

No factory library — each helper takes the session, fills in a minimal
valid row with randomized unique fields, flushes (so server defaults like
id/created_at come back via RETURNING), and returns the ORM instance so
callers can chain straight into the next helper or the row under test.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from argon2 import PasswordHasher
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import Account
from app.auth.models import ApiKey, AuthToken, Session, User
from app.core.clock import Clock
from app.heartbeats.models import Heartbeat, HeartbeatPing
from app.incidents.models import Incident
from app.monitors.models import CheckResult, Monitor
from app.notifications.models import NotificationChannel
from app.status_pages.models import StatusPage


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def make_account(session: AsyncSession, **overrides: Any) -> Account:
    account = Account(**overrides)
    session.add(account)
    await session.flush()
    return account


async def make_user(session: AsyncSession, account_id: uuid.UUID, **overrides: Any) -> User:
    defaults: dict[str, Any] = {
        "account_id": account_id,
        "email": f"{uuid.uuid4().hex}@example.com",
        "password_hash": "argon2-placeholder",
    }
    defaults.update(overrides)
    user = User(**defaults)
    session.add(user)
    await session.flush()
    return user


async def make_user_with_password(
    session: AsyncSession,
    account_id: uuid.UUID,
    password: str,
    hasher: PasswordHasher,
    **overrides: Any,
) -> User:
    """Like make_user, but with a real, verifiable argon2 hash — make_user's
    default password_hash is just a placeholder string, not a real hash."""
    defaults: dict[str, Any] = {"password_hash": hasher.hash(password)}
    defaults.update(overrides)
    return await make_user(session, account_id, **defaults)


async def make_valid_session(
    session: AsyncSession, user_id: uuid.UUID, clock: Clock, **overrides: Any
) -> tuple[str, Session]:
    """Returns (raw_token, row). raw_token is what a test sets as the cookie
    value; row.id is sha256(raw_token).hexdigest() — matching production
    exactly (sessions.id IS the hash, there's no separate token column)."""
    raw_token = secrets.token_urlsafe(32)
    defaults: dict[str, Any] = {
        "id": hashlib.sha256(raw_token.encode()).hexdigest(),
        "user_id": user_id,
        "expires_at": clock.now() + timedelta(days=30),
    }
    defaults.update(overrides)
    row = Session(**defaults)
    session.add(row)
    await session.flush()
    return raw_token, row


async def make_session(session: AsyncSession, user_id: uuid.UUID, **overrides: Any) -> Session:
    defaults: dict[str, Any] = {
        "id": secrets.token_hex(32),
        "user_id": user_id,
        "expires_at": utcnow(),
    }
    defaults.update(overrides)
    row = Session(**defaults)
    session.add(row)
    await session.flush()
    return row


async def make_api_key(session: AsyncSession, account_id: uuid.UUID, **overrides: Any) -> ApiKey:
    defaults: dict[str, Any] = {
        "account_id": account_id,
        "prefix": f"ck_{uuid.uuid4().hex[:12]}",
        "key_hash": uuid.uuid4().hex,
    }
    defaults.update(overrides)
    row = ApiKey(**defaults)
    session.add(row)
    await session.flush()
    return row


async def make_auth_token(session: AsyncSession, user_id: uuid.UUID, **overrides: Any) -> AuthToken:
    defaults: dict[str, Any] = {
        "user_id": user_id,
        "purpose": "verify_email",
        "token_hash": uuid.uuid4().hex,
        "expires_at": utcnow(),
    }
    defaults.update(overrides)
    row = AuthToken(**defaults)
    session.add(row)
    await session.flush()
    return row


async def make_monitor(session: AsyncSession, account_id: uuid.UUID, **overrides: Any) -> Monitor:
    defaults: dict[str, Any] = {
        "account_id": account_id,
        "name": f"monitor-{uuid.uuid4().hex[:8]}",
        "url": f"https://example.com/{uuid.uuid4().hex}",
        "interval_seconds": 120,
        "is_active": True,
        "status": "new",
    }
    defaults.update(overrides)
    monitor = Monitor(**defaults)
    session.add(monitor)
    await session.flush()
    return monitor


async def make_check_result(
    session: AsyncSession, monitor_id: uuid.UUID, **overrides: Any
) -> CheckResult:
    defaults: dict[str, Any] = {"monitor_id": monitor_id, "is_up": True}
    defaults.update(overrides)
    row = CheckResult(**defaults)
    session.add(row)
    await session.flush()
    return row


def make_heartbeat_slug() -> str:
    # secrets.token_urlsafe(16) is 22 base64url characters — matches
    # heartbeats.slug's CHECK (^[A-Za-z0-9_-]{22}$) exactly.
    return secrets.token_urlsafe(16)


async def make_heartbeat(
    session: AsyncSession, account_id: uuid.UUID, **overrides: Any
) -> Heartbeat:
    defaults: dict[str, Any] = {
        "account_id": account_id,
        "name": f"heartbeat-{uuid.uuid4().hex[:8]}",
        "slug": make_heartbeat_slug(),
        "period_seconds": 300,
        "is_active": True,
        "status": "new",
    }
    defaults.update(overrides)
    heartbeat = Heartbeat(**defaults)
    session.add(heartbeat)
    await session.flush()
    return heartbeat


async def make_heartbeat_ping(
    session: AsyncSession, heartbeat_id: uuid.UUID, **overrides: Any
) -> HeartbeatPing:
    defaults: dict[str, Any] = {
        "heartbeat_id": heartbeat_id,
        "kind": "success",
        "ip_hash": uuid.uuid4().hex,
    }
    defaults.update(overrides)
    row = HeartbeatPing(**defaults)
    session.add(row)
    await session.flush()
    return row


async def make_notification_channel(
    session: AsyncSession, account_id: uuid.UUID, **overrides: Any
) -> NotificationChannel:
    defaults: dict[str, Any] = {
        "account_id": account_id,
        "kind": "email",
        "config": {"address": f"{uuid.uuid4().hex}@example.com"},
    }
    defaults.update(overrides)
    channel = NotificationChannel(**defaults)
    session.add(channel)
    await session.flush()
    return channel


async def make_incident(
    session: AsyncSession,
    account_id: uuid.UUID,
    *,
    monitor_id: uuid.UUID | None = None,
    heartbeat_id: uuid.UUID | None = None,
    **overrides: Any,
) -> Incident:
    cause = "http_status" if monitor_id is not None else "heartbeat_missed"
    defaults: dict[str, Any] = {
        "account_id": account_id,
        "monitor_id": monitor_id,
        "heartbeat_id": heartbeat_id,
        "started_at": utcnow(),
        "cause": cause,
    }
    defaults.update(overrides)
    incident = Incident(**defaults)
    session.add(incident)
    await session.flush()
    return incident


async def make_status_page(
    session: AsyncSession, account_id: uuid.UUID, **overrides: Any
) -> StatusPage:
    defaults: dict[str, Any] = {
        "account_id": account_id,
        "slug": f"page-{uuid.uuid4().hex[:12]}",
        "title": "Status",
        "is_public": True,
    }
    defaults.update(overrides)
    page = StatusPage(**defaults)
    session.add(page)
    await session.flush()
    return page
