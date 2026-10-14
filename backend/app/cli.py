"""Dev-only data seeding CLI.

Run via `python -m app.cli <command> ...`, matching the `python -m
app.notifier` convention already used by the other standalone processes.
Refuses outright when ENV=production, before touching the database at all —
this tool exists to make local/test iteration fast and must never run
against a production database (CLAUDE.md).
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.auth.security import build_password_hasher
from app.core.clock import SystemClock
from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.core.errors import ApiError
from app.dev_fixtures import SeedError
from app.dev_fixtures import create_user as _create_user_row
from app.dev_fixtures import seed_monitors as _seed_monitors_rows


async def _run_create_user(email: str, password: str, verified: bool) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        hasher = build_password_hasher(settings)
        clock = SystemClock()
        async with session_factory() as session:
            user = await _create_user_row(
                session,
                email=email,
                password=password,
                verified=verified,
                hasher=hasher,
                clock=clock,
            )
            await session.commit()
            print(
                f"Created user {user.email} "
                f"(id={user.id}, account_id={user.account_id}, verified={verified})."
            )
    finally:
        await engine.dispose()


async def _run_seed_demo(email: str, count: int) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            monitors = await _seed_monitors_rows(
                session, email=email, count=count, settings=settings
            )
            await session.commit()
            print(f"Created {len(monitors)} monitor(s) for {email}:")
            for monitor in monitors:
                suffix = " [paused]" if not monitor.is_active else ""
                print(f"  - {monitor.name} ({monitor.status}){suffix}")
    finally:
        await engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Cronos dev data CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_user_parser = subparsers.add_parser("create-user", help="Create a dev user + account.")
    create_user_parser.add_argument("--email", required=True)
    create_user_parser.add_argument("--password", required=True)
    create_user_parser.add_argument("--verified", action="store_true")

    seed_demo_parser = subparsers.add_parser("seed-demo", help="Seed demo monitors for a user.")
    seed_demo_parser.add_argument("--email", required=True)
    seed_demo_parser.add_argument("--count", type=int, default=6)

    return parser


def main(argv: list[str] | None = None) -> None:
    if get_settings().env == "production":
        raise SystemExit("Refusing to run: ENV=production. This CLI is dev/test-only.")

    args = build_parser().parse_args(argv)
    try:
        if args.command == "create-user":
            asyncio.run(_run_create_user(args.email, args.password, args.verified))
        elif args.command == "seed-demo":
            asyncio.run(_run_seed_demo(args.email, args.count))
    except (ApiError, SeedError) as exc:
        message = exc.detail if isinstance(exc, ApiError) else str(exc)
        print(f"Error: {message}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
