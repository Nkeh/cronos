"""current_principal / current_user / require_verified / API-key extras.

current_principal returns an AuthContext, not a bare User, specifically so
Day 4's API-key auth could be added by rewriting only this one function's
body — which is exactly what happened: if an `Authorization` header is
present, authentication happens ONLY via API key (app.auth.api_keys.
authenticate) — an invalid or revoked key 401s immediately. There is no
fallback to the session cookie just because the header was malformed or the
key didn't match; falling back would let an attacker who injects a bogus
Authorization header silently downgrade to whatever cookie session happens
to be present, defeating the point of having two distinct auth methods.
(CSRFMiddleware already exempts any request carrying an Authorization header
from CSRF checks on the same assumption.)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.constants import SESSION_COOKIE_NAME
from app.auth.models import ApiKey, Session, User
from app.auth.security import hash_token
from app.core.config import Settings
from app.core.db import get_db_session
from app.core.dependencies import get_redis, get_settings_dep
from app.core.errors import ApiError
from app.core.redis import FailOpenRedis


@dataclass(frozen=True)
class AuthContext:
    user: User
    method: Literal["session", "api_key"]
    api_key: ApiKey | None = None


async def _bump_last_seen(db: AsyncSession, token_hash: str, settings: Settings) -> None:
    await db.execute(
        update(Session)
        .where(
            Session.id == token_hash,
            Session.last_seen_at
            < text("now() - make_interval(secs => :bump)").bindparams(
                bump=settings.session_last_seen_bump_seconds
            ),
        )
        .values(last_seen_at=text("now()"))
    )


async def current_principal(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings_dep),
    redis: FailOpenRedis = Depends(get_redis),
) -> AuthContext:
    from app.auth.api_keys import authenticate  # avoids a circular import at module load time

    auth_header = request.headers.get("Authorization")
    if auth_header is not None:
        return await authenticate(auth_header, db, settings, redis)

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
            > text("now() - make_interval(days => :idle)").bindparams(
                idle=settings.session_idle_ttl_days
            ),
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


async def current_session_user(principal: AuthContext = Depends(current_principal)) -> User:
    """For endpoints an API key must never be able to call (e.g. managing
    API keys themselves) — a key presenting itself here is a 403, not a
    silent downgrade to treating it like a session."""
    if principal.method != "session":
        raise ApiError(
            403, "session_required", "This endpoint requires a session, not an API key."
        )
    return principal.user


async def require_verified_session_user(user: User = Depends(current_session_user)) -> User:
    if user.email_verified_at is None:
        raise ApiError(403, "email_not_verified", "Verify your email to continue.")
    return user


def require_scope(scope: str):
    """Session principals carry every scope; an API-key principal must have
    been granted `scope` (or a write scope that implies it)."""

    async def _check(principal: AuthContext = Depends(current_principal)) -> AuthContext:
        from app.auth.api_keys import expand_scopes  # avoids a circular import

        if principal.method == "session":
            return principal
        assert principal.api_key is not None
        if scope not in expand_scopes(principal.api_key.scopes):
            raise ApiError(
                403, "insufficient_scope", f"This API key lacks the '{scope}' scope."
            )
        return principal

    return _check
