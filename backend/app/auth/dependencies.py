"""current_principal / current_user / require_verified.

current_principal returns an AuthContext, not a bare User, specifically so
Day 4's API-key auth can be added by rewriting only this one function's body.

Day 4 rule, recorded now so it's binding before any API-key code exists: if
an `Authorization` header is present, authenticate ONLY by API key — an
invalid or revoked key must 401 immediately. Never fall back to checking the
session cookie just because the header was malformed or the key didn't
match; falling back would let an attacker who injects a bogus Authorization
header silently downgrade to whatever cookie session happens to be present,
defeating the point of having two distinct auth methods. (CSRFMiddleware
already exempts any request carrying an Authorization header from CSRF
checks on the same assumption — Day 4 must keep that assumption true.)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.constants import SESSION_COOKIE_NAME
from app.auth.models import Session, User
from app.auth.security import hash_token
from app.core.config import Settings
from app.core.db import get_db_session
from app.core.dependencies import get_settings_dep
from app.core.errors import ApiError


@dataclass(frozen=True)
class AuthContext:
    user: User
    method: Literal["session", "api_key"]
    api_key: object | None = None  # Day 4 fills this in with the real ApiKey row


async def _bump_last_seen(db: AsyncSession, token_hash: str, settings: Settings) -> None:
    await db.execute(
        update(Session)
        .where(
            Session.id == token_hash,
            Session.last_seen_at
            < text(f"now() - interval '{settings.session_last_seen_bump_seconds} seconds'"),
        )
        .values(last_seen_at=text("now()"))
    )


async def current_principal(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings_dep),
) -> AuthContext:
    # Day 4: if request.headers.get("Authorization") is present, authenticate
    # ONLY by API key here — never fall through to the cookie below.
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_token:
        raise HTTPException(401)

    token_hash = hash_token(raw_token)
    stmt = (
        select(User)
        .select_from(Session)
        .join(User, User.id == Session.user_id)
        .where(
            Session.id == token_hash,
            Session.expires_at > text("now()"),
            Session.last_seen_at
            > text(f"now() - interval '{settings.session_idle_ttl_days} days'"),
        )
    )
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        raise HTTPException(401)

    await _bump_last_seen(db, token_hash, settings)
    await db.commit()

    return AuthContext(user=user, method="session")


async def current_user(principal: AuthContext = Depends(current_principal)) -> User:
    return principal.user


async def require_verified(user: User = Depends(current_user)) -> User:
    if user.email_verified_at is None:
        raise ApiError(403, "email_not_verified", "Verify your email to continue.")
    return user
