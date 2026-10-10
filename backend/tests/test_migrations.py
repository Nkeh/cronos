from __future__ import annotations

import os
import subprocess

import pytest


def _run_alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["alembic", *args],
        cwd="/app",
        env=os.environ,
        capture_output=True,
        text=True,
    )


def test_no_migration_drift() -> None:
    """`alembic check` diffs the live DB against the models — no missing or
    extra tables/columns/indexes/FKs. It does NOT diff CHECK constraint
    bodies or anything about triggers/functions (invisible to its
    comparator) — that's what the hand-written constraint tests are for.
    """
    result = _run_alembic("check")
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.migration
def test_migration_round_trip() -> None:
    """downgrade base -> upgrade head, clean. Destructive mid-session (drops
    every table), so this is excluded from the default run — see pyproject
    .toml's `addopts` — and run explicitly:
    docker compose exec api pytest -q -m migration
    """
    down = _run_alembic("downgrade", "base")
    assert down.returncode == 0, down.stdout + down.stderr

    up = _run_alembic("upgrade", "head")
    assert up.returncode == 0, up.stdout + up.stderr
