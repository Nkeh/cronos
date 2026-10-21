"""The 9 auth endpoints.

Every route that writes calls `await db.commit()` itself, explicitly, before
scheduling any BackgroundTask and before returning — see core/db.py's
get_db_session docstring for why this isn't left to dependency teardown.
"""

from __future__ import annotations

from datetime import timedelta

import structlog
from argon2 import PasswordHasher
from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import Account
from app.auth.constants import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from app.auth.dependencies import current_user
from app.auth.models import AuthToken, Session, User
from app.auth.rate_limit import (
    get_client_ip,
    login_failure_keys,
    login_rate_limit,
    record_failure,
    reset_request_rate_limit,
    signup_rate_limit,
    verify_resend_rate_limit,
)
from app.auth.schemas import (
    LoginRequest,
    LogoutRequest,
    ResetRequest,
    ResetRequestRequest,
    ResetRequestResponse,
    ResetResponse,
    SignupRequest,
    SignupResponse,
    UserPublic,
    VerifyRequest,
    VerifyResendRequest,
    VerifyResendResponse,
    VerifyResponse,
)
from app.auth.security import (
    hash_email,
    hash_password,
    hash_token,
    needs_rehash,
    new_raw_token,
    validate_password_policy,
    verify_password,
)
from app.core.clock import Clock
from app.core.config import Settings
from app.core.db import get_db_session
from app.core.dependencies import (
    get_clock,
    get_dummy_password_hash,
    get_email_sender,
    get_password_hasher,
    get_redis,
    get_settings_dep,
)
from app.core.email import (
    EmailSender,
    render_already_registered_email,
    render_reset_email,
    render_verify_email,
)
from app.core.errors import ApiError
from app.core.redis import FailOpenRedis
from app.notifications.models import NotificationChannel

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_SIGNUP_MESSAGE = "Check your email to verify your account."


def _set_csrf_cookie(response: Response, settings: Settings) -> None:
    response.set_cookie(
        CSRF_COOKIE_NAME,
        new_raw_token(),
        httponly=False,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


@router.get("/csrf")
async def get_csrf(response: Response, settings: Settings = Depends(get_settings_dep)) -> dict:
    _set_csrf_cookie(response, settings)
    return {}


@router.post("/signup", response_model=SignupResponse, status_code=201)
async def signup(
    payload: SignupRequest,
    background_tasks: BackgroundTasks,
    _rate_limit: None = Depends(signup_rate_limit),
    db: AsyncSession = Depends(get_db_session),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings_dep),
    hasher: PasswordHasher = Depends(get_password_hasher),
    email_sender: EmailSender = Depends(get_email_sender),
) -> SignupResponse:
    validate_password_policy(payload.password)

    existing = (
        await db.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()

    if existing is not None:
        # Same timing-safety principle as login's dummy hash: this branch
        # must take comparable time to the real-signup branch below, or the
        # two are distinguishable by response time, defeating the point of
        # returning an identical body.
        await hash_password(hasher, payload.password)
        background_tasks.add_task(email_sender.send, render_already_registered_email(to=existing.email))
        logger.info("signup_duplicate", user_id=str(existing.id))
        return SignupResponse(message=_SIGNUP_MESSAGE)

    account = Account()
    db.add(account)
    await db.flush()

    user = User(
        account_id=account.id,
        email=payload.email,
        password_hash=await hash_password(hasher, payload.password),
    )
    db.add(user)
    await db.flush()

    raw_token = new_raw_token()
    db.add(
        AuthToken(
            user_id=user.id,
            purpose="verify_email",
            token_hash=hash_token(raw_token),
            expires_at=clock.now() + timedelta(hours=settings.verify_token_ttl_hours),
        )
    )
    await db.commit()

    link = f"{settings.public_origin}/verify?token={raw_token}"
    background_tasks.add_task(email_sender.send, render_verify_email(to=user.email, link=link))
    logger.info("signup_succeeded", user_id=str(user.id))
    return SignupResponse(message=_SIGNUP_MESSAGE)


@router.post("/verify", response_model=VerifyResponse)
async def verify(
    payload: VerifyRequest,
    db: AsyncSession = Depends(get_db_session),
    clock: Clock = Depends(get_clock),
) -> VerifyResponse:
    token_hash = hash_token(payload.token)
    stmt = select(AuthToken).where(
        AuthToken.token_hash == token_hash,
        AuthToken.purpose == "verify_email",
        AuthToken.used_at.is_(None),
        AuthToken.expires_at > text("now()"),
    )
    token_row = (await db.execute(stmt)).scalar_one_or_none()
    if token_row is None:
        # One generic code for bad/expired/used/wrong-purpose — distinguishing
        # them in the response would let an attacker probe token validity.
        raise ApiError(400, "invalid_token", "Invalid or expired token.")

    user = await db.get(User, token_row.user_id)
    user.email_verified_at = clock.now()
    token_row.used_at = clock.now()
    # Day 9, confirmed with Oryn: verifying the account email auto-creates a verified `email`
    # channel for that address with is_default=true, same transaction -- the account alerts
    # somewhere from the moment it can run monitors at all, with no separate setup step.
    db.add(
        NotificationChannel(
            account_id=user.account_id,
            kind="email",
            name="Account email",
            config={"address": user.email},
            is_default=True,
            verified_at=clock.now(),
        )
    )
    await db.commit()
    logger.info("email_verified", user_id=str(user.id))
    return VerifyResponse(message="Email verified.")


@router.post("/verify/resend", response_model=VerifyResendResponse)
async def verify_resend(
    payload: VerifyResendRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(current_user),
    _rate_limit: None = Depends(verify_resend_rate_limit),
    db: AsyncSession = Depends(get_db_session),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings_dep),
    email_sender: EmailSender = Depends(get_email_sender),
) -> VerifyResendResponse:
    raw_token = new_raw_token()
    db.add(
        AuthToken(
            user_id=user.id,
            purpose="verify_email",
            token_hash=hash_token(raw_token),
            expires_at=clock.now() + timedelta(hours=settings.verify_token_ttl_hours),
        )
    )
    await db.commit()

    link = f"{settings.public_origin}/verify?token={raw_token}"
    background_tasks.add_task(email_sender.send, render_verify_email(to=user.email, link=link))
    return VerifyResendResponse(message="Verification email sent.")


@router.post("/login", response_model=UserPublic)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    _rate_limit: None = Depends(login_rate_limit),
    db: AsyncSession = Depends(get_db_session),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings_dep),
    hasher: PasswordHasher = Depends(get_password_hasher),
    dummy_hash: str = Depends(get_dummy_password_hash),
    redis: FailOpenRedis = Depends(get_redis),
) -> UserPublic:
    ip = get_client_ip(request, settings.trusted_proxy_ips_set)
    email_ip_key, email_key = login_failure_keys(payload.email, ip)
    email_hash = hash_email(payload.email)

    async def _record_failure() -> None:
        await record_failure(
            redis,
            key=email_ip_key,
            window_seconds=settings.rate_limit_login_email_ip_failures_window_seconds,
        )
        await record_failure(
            redis,
            key=email_key,
            window_seconds=settings.rate_limit_login_email_failures_window_seconds,
        )

    user = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()

    if user is None:
        await verify_password(hasher, dummy_hash, payload.password)  # timing only, discarded
        await _record_failure()
        logger.info("login_failed", email_hash=email_hash)
        raise ApiError(401, "invalid_credentials", "Invalid email or password.")

    if not await verify_password(hasher, user.password_hash, payload.password):
        await _record_failure()
        logger.info("login_failed", user_id=str(user.id), email_hash=email_hash)
        raise ApiError(401, "invalid_credentials", "Invalid email or password.")

    # Success: clear this (email, IP) pair's failure count. The per-email/
    # all-IPs ceiling is deliberately left to expire on its own TTL.
    await redis.delete_key(email_ip_key)

    if await needs_rehash(hasher, user.password_hash):
        user.password_hash = await hash_password(hasher, payload.password)

    raw_token = new_raw_token()
    db.add(
        Session(
            id=hash_token(raw_token),
            user_id=user.id,
            expires_at=clock.now() + timedelta(days=settings.session_absolute_ttl_days),
            user_agent=request.headers.get("User-Agent"),
        )
    )
    await db.commit()

    response.set_cookie(
        SESSION_COOKIE_NAME,
        raw_token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
        max_age=settings.session_absolute_ttl_days * 86400,
    )
    _set_csrf_cookie(response, settings)

    account = await db.get(Account, user.account_id)
    logger.info("login_succeeded", user_id=str(user.id))
    return UserPublic(
        user_id=user.id,
        email=user.email,
        email_verified=user.email_verified_at is not None,
        account_id=user.account_id,
        plan=account.plan,
    )


@router.post("/logout", status_code=204)
async def logout(
    payload: LogoutRequest,
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings_dep),
) -> None:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token:
        await db.execute(delete(Session).where(Session.id == hash_token(raw_token)))
        await db.commit()
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    _set_csrf_cookie(response, settings)
    logger.info("logout_succeeded", user_id=str(user.id))


@router.post("/reset-request", response_model=ResetRequestResponse, status_code=202)
async def reset_request(
    payload: ResetRequestRequest,
    background_tasks: BackgroundTasks,
    _rate_limit: None = Depends(reset_request_rate_limit),
    db: AsyncSession = Depends(get_db_session),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings_dep),
    email_sender: EmailSender = Depends(get_email_sender),
) -> ResetRequestResponse:
    user = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()

    if user is not None:
        raw_token = new_raw_token()
        db.add(
            AuthToken(
                user_id=user.id,
                purpose="reset_password",
                token_hash=hash_token(raw_token),
                expires_at=clock.now() + timedelta(hours=settings.reset_token_ttl_hours),
            )
        )
        await db.commit()
        link = f"{settings.public_origin}/reset?token={raw_token}"
        background_tasks.add_task(email_sender.send, render_reset_email(to=user.email, link=link))
        logger.info("reset_requested", user_id=str(user.id))

    return ResetRequestResponse(message="If that email exists, a reset link has been sent.")


@router.post("/reset", response_model=ResetResponse)
async def reset(
    payload: ResetRequest,
    db: AsyncSession = Depends(get_db_session),
    clock: Clock = Depends(get_clock),
    hasher: PasswordHasher = Depends(get_password_hasher),
) -> ResetResponse:
    token_hash = hash_token(payload.token)
    stmt = select(AuthToken).where(
        AuthToken.token_hash == token_hash,
        AuthToken.purpose == "reset_password",
        AuthToken.used_at.is_(None),
        AuthToken.expires_at > text("now()"),
    )
    token_row = (await db.execute(stmt)).scalar_one_or_none()
    if token_row is None:
        raise ApiError(400, "invalid_token", "Invalid or expired token.")

    validate_password_policy(payload.password)

    user = await db.get(User, token_row.user_id)
    user.password_hash = await hash_password(hasher, payload.password)
    token_row.used_at = clock.now()
    await db.execute(delete(Session).where(Session.user_id == user.id))
    await db.commit()
    logger.info("password_reset", user_id=str(user.id))
    return ResetResponse(message="Password reset.")


@router.get("/me", response_model=UserPublic)
async def me(
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db_session)
) -> UserPublic:
    account = await db.get(Account, user.account_id)
    return UserPublic(
        user_id=user.id,
        email=user.email,
        email_verified=user.email_verified_at is not None,
        account_id=user.account_id,
        plan=account.plan,
    )
