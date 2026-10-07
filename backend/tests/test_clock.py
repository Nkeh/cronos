from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.clock import FrozenClock, SystemClock


def test_frozen_clock_returns_a_fixed_instant() -> None:
    at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    clock = FrozenClock(at=at)
    assert clock.now() == at
    assert clock.now() == at  # calling it again doesn't move time


def test_frozen_clock_advances_only_when_told_to() -> None:
    at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    clock = FrozenClock(at=at)
    clock.advance(timedelta(seconds=30))
    assert clock.now() == at + timedelta(seconds=30)


def test_system_clock_returns_timezone_aware_utc_now() -> None:
    clock = SystemClock()
    now = clock.now()
    assert now.tzinfo is not None
