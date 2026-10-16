"""The Probe protocol and today's stub implementation.

Day 7 replaces StubProbe with the real guarded HTTP probe behind this same Protocol -- nothing
else in the runner needs to change.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Literal, Protocol

from app.engine.claim import ClaimedMonitor


@dataclass(frozen=True, slots=True)
class ProbeResult:
    is_up: bool
    status_code: int | None
    response_time_ms: int
    error: str | None
    timings: dict | None = None
    error_kind: str | None = None


class Probe(Protocol):
    async def check(self, monitor: ClaimedMonitor) -> ProbeResult: ...


class StubProbe:
    """Explicit constructor args, not a hidden Settings read -- so tests and the live load
    test fully control delay/outcome by constructing their own instance. runner.py builds the
    default instance from Settings for the real process."""

    def __init__(
        self,
        *,
        delay_min_ms: int,
        delay_max_ms: int,
        outcome: Literal["up", "down"],
    ) -> None:
        self._delay_min_ms = delay_min_ms
        self._delay_max_ms = delay_max_ms
        self._outcome = outcome

    async def check(self, monitor: ClaimedMonitor) -> ProbeResult:
        delay_ms = random.randint(self._delay_min_ms, self._delay_max_ms)
        await asyncio.sleep(delay_ms / 1000)
        is_up = self._outcome == "up"
        return ProbeResult(
            is_up=is_up,
            status_code=200 if is_up else None,
            response_time_ms=delay_ms,
            error=None if is_up else "stub_down",
        )
