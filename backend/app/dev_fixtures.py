"""Shared fixture-creation logic for the dev CLI and the dev-only HTTP router.

Both app.cli and app.dev.router call into these functions so there is exactly
one place that knows how to build a valid user/account or a batch of demo
monitors — never duplicated between the two entry points. Neither entry point
is reachable in production: the CLI refuses to run (see app/cli.py), and the
HTTP router is never mounted (see app/main.py).
"""

from __future__ import annotations

import httpx
from argon2 import PasswordHasher
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import Account
from app.auth.models import User
from app.auth.security import hash_password, validate_password_policy
from app.core.clock import Clock
from app.core.config import Settings
from app.engine import ssrf_policy
from app.monitors.models import Monitor
from app.plans.config import get_plan

CHAOS_BASE_URL = "http://chaos:8000"


class SeedError(Exception):
    """Raised for fixture-creation failures the CLI/router should report cleanly
    (missing user, over the plan limit, duplicate email) rather than as a 500
    or an uncaught traceback."""


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    verified: bool,
    hasher: PasswordHasher,
    clock: Clock,
) -> User:
    """Mirrors app.auth.router.signup's write sequence exactly, minus the
    verify-email token/send (verified status is set directly instead)."""
    validate_password_policy(password)

    existing = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existing is not None:
        raise SeedError(f"A user with email {email!r} already exists.")

    account = Account()
    session.add(account)
    await session.flush()

    user = User(
        account_id=account.id,
        email=email,
        password_hash=await hash_password(hasher, password),
        email_verified_at=clock.now() if verified else None,
    )
    session.add(user)
    await session.flush()
    return user


async def delete_account_by_email(session: AsyncSession, email: str) -> bool:
    """Deletes the account owning `email` — cascades to the user row and every monitor/
    heartbeat/etc via each table's FK ondelete="CASCADE". Used by Playwright's global-setup to
    make fixture accounts idempotent to recreate against the persistent dev database (which,
    unlike the test database, is never wiped between runs). Returns False if no such user
    exists (nothing to delete), True otherwise."""
    user = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if user is None:
        return False
    account = await session.get(Account, user.account_id)
    if account is not None:
        await session.delete(account)
    return True


async def _get_user_by_email(session: AsyncSession, email: str) -> User:
    user = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if user is None:
        raise SeedError(f"No user with email {email!r} — create one first.")
    return user


async def _configure_chaos(path: str, **control: object) -> None:
    async with httpx.AsyncClient(base_url=CHAOS_BASE_URL, timeout=5.0) as client:
        response = await client.post("/_control", json={"path": path, **control})
        response.raise_for_status()


async def seed_monitors(
    session: AsyncSession,
    *,
    email: str,
    count: int,
    settings: Settings,
) -> list[Monitor]:
    """Creates `count` monitors for the account owning `email`. The first few
    (up to 4) form a fixed "demo" shape — one healthy, one slow, one failing,
    one paused, all pointed at the chaos service — so the monitor UI has
    something interesting to render; anything beyond that is plain filler,
    used by the 15-monitor plan-limit test."""
    user = await _get_user_by_email(session, email)
    account = await session.get(Account, user.account_id)
    assert account is not None
    plan = get_plan(account.plan)

    existing_rows = (
        (await session.execute(select(Monitor).where(Monitor.account_id == account.id)))
        .scalars()
        .all()
    )
    if len(existing_rows) + count > plan.max_monitors:
        raise SeedError(
            f"Seeding {count} would put this account over the {plan.name} plan's "
            f"{plan.max_monitors}-monitor limit ({len(existing_rows)} already exist)."
        )

    allow_hosts = settings.ssrf_allow_hosts_set
    created: list[Monitor] = []

    def add_monitor(name: str, url: str, *, paused: bool = False) -> None:
        parsed = ssrf_policy.normalize_and_validate_url(url, allow_hosts=allow_hosts)
        monitor = Monitor(
            account_id=account.id,
            name=name,
            url=parsed.normalized_url,
            interval_seconds=300,
            is_active=not paused,
            status="paused" if paused else "new",
        )
        session.add(monitor)
        created.append(monitor)

    if count >= 1:
        add_monitor("Chaos — healthy", f"{CHAOS_BASE_URL}/health")
    if count >= 2:
        await _configure_chaos("/slow", mode="slow", delay_ms=4000)
        add_monitor("Chaos — slow", f"{CHAOS_BASE_URL}/slow")
    if count >= 3:
        await _configure_chaos("/fail", mode="down", status_code=500)
        add_monitor("Chaos — failing", f"{CHAOS_BASE_URL}/fail")
    if count >= 4:
        add_monitor("Chaos — paused", f"{CHAOS_BASE_URL}/health", paused=True)
    for i in range(5, count + 1):
        add_monitor(f"Demo monitor {i}", f"{CHAOS_BASE_URL}/demo-{i}")

    await session.flush()
    return created
