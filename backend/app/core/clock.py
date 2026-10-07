"""An injectable clock so business logic never calls datetime.now() directly.

Postgres is the clock for all data comparisons (see core/db.py and every
`now()` in SQL); this clock exists for the Python-side logic that still needs
"now" — e.g. computing a deadline to pass into a query — and lets tests freeze
time instead of racing the real clock.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FrozenClock:
    """Returns a fixed instant until explicitly advanced."""

    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at

    def advance(self, delta: timedelta) -> None:
        self._at += delta
