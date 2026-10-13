"""Client-IP resolution plus the per-endpoint rate-limit dependencies.

Login's limits are split across two moments deliberately (see the module
docstring on the login route in router.py): the per-IP "every attempt" limit
and the failure-ceiling *pre-checks* both run here, before any password
verification; *recording* a failure (or clearing one on success) happens in
the route itself, after the outcome is known.
"""

from __future__ import annotations

from fastapi import Depends, Request

from app.auth.dependencies import current_user
from app.auth.models import User
from app.auth.schemas import LoginRequest, ResetRequestRequest
from app.auth.security import hash_email
from app.core.config import Settings
from app.core.dependencies import get_redis, get_settings_dep
from app.core.errors import ApiError
from app.core.redis import FailOpenRedis


def get_client_ip(request: Request, trusted_proxy_ips: frozenset[str]) -> str:
    """Trusts X-Forwarded-For only when the immediate peer is a known proxy.

    Two independent trust layers exist on purpose: uvicorn's own
    --proxy-headers/--forwarded-allow-ips already rewrites scope["client"]
    before the app sees the request when the real deployment is behind
    Caddy; this function is also the ONLY layer active under the test
    suite's ASGITransport, which bypasses uvicorn entirely. Either way, an
    untrusted peer's X-Forwarded-For header is always ignored.
    """
    peer_ip = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded and peer_ip in trusted_proxy_ips:
        return forwarded.split(",")[0].strip()
    return peer_ip


async def enforce_rate_limit(
    redis: FailOpenRedis, *, key: str, max_requests: int, window_seconds: int
) -> None:
    """Increments `key` and raises 429 if it's now over `max_requests`.

    Use for "every attempt counts" limits (per-IP on login/signup/etc).
    """
    result = await redis.incr_with_ttl(key, window_seconds)
    if result is None:
        return  # Redis down: fail open.
    count, ttl = result
    if count > max_requests:
        raise ApiError(
            429, "rate_limited", "Too many requests.", headers={"Retry-After": str(max(ttl, 1))}
        )


async def check_not_over_limit(
    redis: FailOpenRedis, *, key: str, max_requests: int, window_seconds: int
) -> None:
    """Reads `key` WITHOUT incrementing and raises 429 if already at/over the
    limit. Use for failure-only ceilings, checked before the attempt that
    might fail is even made.
    """
    count = await redis.get_count(key)
    if count is None:
        return  # Redis down: fail open.
    if count >= max_requests:
        ttl = await redis.get_ttl(key)
        retry_after = ttl if ttl and ttl > 0 else window_seconds
        raise ApiError(
            429, "rate_limited", "Too many requests.", headers={"Retry-After": str(retry_after)}
        )


async def record_failure(redis: FailOpenRedis, *, key: str, window_seconds: int) -> None:
    """Increments a failure-only counter. The pre-check already happened
    (check_not_over_limit) — this just records; it never itself raises."""
    await redis.incr_with_ttl(key, window_seconds)


def login_failure_keys(email: str, ip: str) -> tuple[str, str]:
    email_hash = hash_email(email)
    return (
        f"ratelimit:login:failures:email_ip:{email_hash}:{ip}",
        f"ratelimit:login:failures:email:{email_hash}",
    )


async def signup_rate_limit(
    request: Request,
    redis: FailOpenRedis = Depends(get_redis),
    settings: Settings = Depends(get_settings_dep),
) -> None:
    ip = get_client_ip(request, settings.trusted_proxy_ips_set)
    await enforce_rate_limit(
        redis,
        key=f"ratelimit:signup:ip:{ip}",
        max_requests=settings.rate_limit_signup_ip_max,
        window_seconds=settings.rate_limit_signup_ip_window_seconds,
    )


async def login_rate_limit(
    request: Request,
    payload: LoginRequest,
    redis: FailOpenRedis = Depends(get_redis),
    settings: Settings = Depends(get_settings_dep),
) -> None:
    ip = get_client_ip(request, settings.trusted_proxy_ips_set)
    await enforce_rate_limit(
        redis,
        key=f"ratelimit:login:ip:{ip}",
        max_requests=settings.rate_limit_login_ip_max,
        window_seconds=settings.rate_limit_login_ip_window_seconds,
    )
    email_ip_key, email_key = login_failure_keys(payload.email, ip)
    await check_not_over_limit(
        redis,
        key=email_ip_key,
        max_requests=settings.rate_limit_login_email_ip_failures_max,
        window_seconds=settings.rate_limit_login_email_ip_failures_window_seconds,
    )
    await check_not_over_limit(
        redis,
        key=email_key,
        max_requests=settings.rate_limit_login_email_failures_max,
        window_seconds=settings.rate_limit_login_email_failures_window_seconds,
    )


async def reset_request_rate_limit(
    request: Request,
    payload: ResetRequestRequest,
    redis: FailOpenRedis = Depends(get_redis),
    settings: Settings = Depends(get_settings_dep),
) -> None:
    ip = get_client_ip(request, settings.trusted_proxy_ips_set)
    email_hash = hash_email(payload.email)
    await enforce_rate_limit(
        redis,
        key=f"ratelimit:reset-request:email:{email_hash}",
        max_requests=settings.rate_limit_reset_request_email_max,
        window_seconds=settings.rate_limit_reset_request_email_window_seconds,
    )
    await enforce_rate_limit(
        redis,
        key=f"ratelimit:reset-request:ip:{ip}",
        max_requests=settings.rate_limit_reset_request_ip_max,
        window_seconds=settings.rate_limit_reset_request_ip_window_seconds,
    )


async def verify_resend_rate_limit(
    user: User = Depends(current_user),
    redis: FailOpenRedis = Depends(get_redis),
    settings: Settings = Depends(get_settings_dep),
) -> None:
    await enforce_rate_limit(
        redis,
        key=f"ratelimit:verify-resend:user:{user.id}",
        max_requests=settings.rate_limit_verify_resend_user_max,
        window_seconds=settings.rate_limit_verify_resend_user_window_seconds,
    )
