"""Password hashing, token hashing, password policy, the dummy hash.

Hash/verify always run off the event loop (anyio.to_thread.run_sync) — argon2
is deliberately slow, and blocking the loop for that long would stall every
other request being served by this process.
"""

from __future__ import annotations

import hashlib
import secrets
from pathlib import Path

import anyio
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerifyMismatchError

from app.core.config import Settings
from app.core.errors import ApiError

_COMMON_PASSWORDS_PATH = Path(__file__).parent / "common_passwords.txt"
COMMON_PASSWORDS: frozenset[str] = frozenset(
    line.strip().lower()
    for line in _COMMON_PASSWORDS_PATH.read_text(encoding="utf-8").splitlines()
    if line.strip()
)

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128


def build_password_hasher(settings: Settings) -> PasswordHasher:
    return PasswordHasher(
        time_cost=settings.argon2_time_cost,
        memory_cost=settings.argon2_memory_cost,
        parallelism=settings.argon2_parallelism,
        hash_len=settings.argon2_hash_len,
        salt_len=settings.argon2_salt_len,
    )


def build_dummy_hash(hasher: PasswordHasher) -> str:
    """A real hash of a random, unknowable value, using the SAME hasher
    instance that's actually configured — its cost params can never drift
    from whatever ARGON2_* settings are active (cheap in tests, real in prod),
    so the login timing-safety trick holds in both environments automatically.
    """
    return hasher.hash(secrets.token_urlsafe(32))


async def hash_password(hasher: PasswordHasher, password: str) -> str:
    return await anyio.to_thread.run_sync(hasher.hash, password)


async def verify_password(hasher: PasswordHasher, stored_hash: str, password: str) -> bool:
    def _verify() -> bool:
        try:
            hasher.verify(stored_hash, password)
            return True
        except (VerifyMismatchError, InvalidHash):
            return False

    return await anyio.to_thread.run_sync(_verify)


async def needs_rehash(hasher: PasswordHasher, stored_hash: str) -> bool:
    return await anyio.to_thread.run_sync(hasher.check_needs_rehash, stored_hash)


def validate_password_policy(password: str) -> None:
    if not (MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH):
        raise ApiError(
            400,
            "weak_password",
            f"Password must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters.",
            field="password",
        )
    if password.strip().lower() in COMMON_PASSWORDS:
        raise ApiError(400, "weak_password", "This password is too common.", field="password")


def new_raw_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def hash_email(email: str) -> str:
    """Used for both rate-limit keys and log lines — the raw address is
    never logged or used as a Redis key, only this hash (see CLAUDE.md)."""
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()
