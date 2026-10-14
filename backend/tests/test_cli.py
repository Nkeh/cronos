"""Tests for the dev CLI (app.cli) and its shared fixture logic (app.dev_fixtures).

The create-user/seed-demo commands themselves are exercised via subprocess
(the exact `python -m app.cli ...` invocation Oryn runs), since that's the
actual deliverable; the plan-limit edge case and basic shape of
seed_monitors are exercised directly against app.dev_fixtures for speed and
precision.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.core.config import get_settings
from app.dev_fixtures import SeedError, seed_monitors
from app.monitors.models import Monitor
from tests.helpers import make_account, make_monitor


def _run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "app.cli", *args],
        cwd="/app",
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
    )


async def test_create_user_cli_creates_verified_user(db_session: AsyncSession) -> None:
    email = f"cli-{uuid.uuid4().hex[:8]}@example.com"
    result = _run_cli("create-user", "--email", email, "--password", "CorrectHorseBattery9", "--verified")
    assert result.returncode == 0, result.stderr

    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    assert user.email_verified_at is not None


async def test_create_user_cli_without_verified_leaves_unverified(db_session: AsyncSession) -> None:
    email = f"cli-{uuid.uuid4().hex[:8]}@example.com"
    result = _run_cli("create-user", "--email", email, "--password", "CorrectHorseBattery9")
    assert result.returncode == 0, result.stderr

    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    assert user.email_verified_at is None


async def test_create_user_cli_refuses_in_production(db_session: AsyncSession) -> None:
    email = f"cli-{uuid.uuid4().hex[:8]}@example.com"
    result = _run_cli(
        "create-user",
        "--email",
        email,
        "--password",
        "CorrectHorseBattery9",
        "--verified",
        env={"ENV": "production"},
    )
    assert result.returncode != 0
    assert "production" in result.stderr.lower()

    existing = (
        await db_session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    assert existing is None


async def test_seed_demo_cli_creates_monitors_with_one_paused(db_session: AsyncSession) -> None:
    email = f"cli-{uuid.uuid4().hex[:8]}@example.com"
    create_result = _run_cli("create-user", "--email", email, "--password", "CorrectHorseBattery9", "--verified")
    assert create_result.returncode == 0, create_result.stderr

    seed_result = _run_cli("seed-demo", "--email", email, "--count", "4")
    assert seed_result.returncode == 0, seed_result.stderr

    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    monitors = (
        (await db_session.execute(select(Monitor).where(Monitor.account_id == user.account_id)))
        .scalars()
        .all()
    )
    assert len(monitors) == 4
    assert sum(1 for m in monitors if not m.is_active) == 1


async def test_seed_monitors_rejects_over_plan_limit(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    for _ in range(15):
        await make_monitor(db_session, account.id)
    await db_session.flush()

    user_email = f"seed-{uuid.uuid4().hex[:8]}@example.com"
    db_session.add(
        User(account_id=account.id, email=user_email, password_hash="argon2-placeholder")
    )
    await db_session.flush()

    with pytest.raises(SeedError, match="over the launch plan"):
        await seed_monitors(db_session, email=user_email, count=1, settings=get_settings())
