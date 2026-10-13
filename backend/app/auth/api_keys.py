"""API-key format, scope vocabulary, and authentication.

Plays the same role for API keys that security.py plays for passwords and
session tokens: the actual byte-level mechanics live here, while
dependencies.py wires the result into the request pipeline.
"""

from __future__ import annotations

import hmac
import re
import secrets
from typing import TYPE_CHECKING

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import ApiKey, User
from app.auth.security import hash_token, new_raw_token
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.redis import FailOpenRedis
from app.auth.rate_limit import enforce_rate_limit

if TYPE_CHECKING:
    from app.auth.dependencies import AuthContext

SCOPE_RESOURCES = ("monitors", "heartbeats", "incidents", "channels", "status_pages")
SCOPE_LEVELS = ("read", "write")
ALL_SCOPES: frozenset[str] = frozenset(
    f"{resource}:{level}" for resource in SCOPE_RESOURCES for level in SCOPE_LEVELS
)

_KEY_PREFIX_HEX_CHARS = 8
_TOKEN_RE = re.compile(r"^cronos_([0-9a-f]{8})_(.+)$")


def _invalid() -> ApiError:
    # A fresh instance each time — ApiError carries no per-request state, but
    # raising a shared singleton instance repeatedly is needlessly confusing
    # in tracebacks/logs.
    return ApiError(401, "invalid_api_key", "Invalid API key.")


def expand_scopes(granted: list[str]) -> frozenset[str]:
    """write implies read: 'monitors:write' also grants 'monitors:read'."""
    expanded: set[str] = set(granted)
    for scope in granted:
        resource, _, level = scope.partition(":")
        if level == "write":
            expanded.add(f"{resource}:read")
    return frozenset(expanded)


def generate_api_key() -> tuple[str, str, str]:
    """-> (full_raw_key, prefix, key_hash).

    Format: cronos_<8-hex-prefix>_<32-byte urlsafe secret>. prefix is stored
    UNIQUE and used for lookup; key_hash = sha256(full_raw_key), the same
    fast hash used for session tokens (high-entropy keys, so a fast hash is
    the correct choice — unlike passwords).
    """
    secret = new_raw_token()
    prefix = secrets.token_hex(_KEY_PREFIX_HEX_CHARS // 2)
    full = f"cronos_{prefix}_{secret}"
    return full, prefix, hash_token(full)


def parse_bearer_token(header: str) -> tuple[str, str] | None:
    """Returns (prefix, full_raw_key) if header is syntactically
    `Bearer cronos_<8 hex>_<rest>`, else None."""
    if not header.startswith("Bearer "):
        return None
    candidate = header[len("Bearer ") :].strip()
    match = _TOKEN_RE.match(candidate)
    if not match:
        return None
    return match.group(1), candidate


async def authenticate(
    auth_header: str,
    db: AsyncSession,
    settings: Settings,
    redis: FailOpenRedis,
) -> "AuthContext":
    from app.auth.dependencies import AuthContext  # deferred: avoids a circular import

    parsed = parse_bearer_token(auth_header)
    if parsed is None:
        raise _invalid()
    prefix, full_key = parsed

    row = (await db.execute(select(ApiKey).where(ApiKey.prefix == prefix))).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        raise _invalid()
    if not hmac.compare_digest(hash_token(full_key), row.key_hash):
        raise _invalid()

    # A key must always resolve through its creator, never through "the
    # account's user" or any other fallback — if the creator was deleted
    # (created_by_user_id -> NULL via ON DELETE SET NULL) the key is dead.
    if row.created_by_user_id is None:
        raise _invalid()
    user = await db.get(User, row.created_by_user_id)
    if user is None:
        raise _invalid()

    # Enforced here, inside authentication itself, so the limit applies
    # uniformly to every router an API key can reach — present and future —
    # with nothing to remember to attach per-router.
    await enforce_rate_limit(
        redis,
        key=f"ratelimit:apikey:{row.id}",
        max_requests=settings.rate_limit_api_key_max,
        window_seconds=settings.rate_limit_api_key_window_seconds,
    )

    await db.execute(
        update(ApiKey)
        .where(
            ApiKey.id == row.id,
            (ApiKey.last_used_at.is_(None))
            | (
                ApiKey.last_used_at
                < text("now() - make_interval(secs => :bump)").bindparams(
                    bump=settings.session_last_seen_bump_seconds
                )
            ),
        )
        .values(last_used_at=text("now()"))
    )
    await db.commit()

    return AuthContext(user=user, method="api_key", api_key=row)
