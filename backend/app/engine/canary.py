"""Checker self-health. Each runner probes a handful of known-good URLs through the SAME Probe
it uses for real monitors (so canaries are guarded/timed the same way), on a fixed schedule
driven from the main tick loop -- NOT a second run_tick_loop (see runner.py's comment on why:
two concurrent run_tick_loop calls would silently race for SIGTERM/SIGINT ownership).

Degraded (>= 2 of 3 failed, generalized) means Cronos itself can't be trusted to judge the
world: every result this runner writes gets suppressed (see app/engine/state.py) until the
canaries recover. This is the mechanism behind CLAUDE.md's promise that Cronos never blames a
user's service for its own failure.
"""

from __future__ import annotations

import asyncio
import math
import uuid
from datetime import datetime, timezone
from typing import Sequence

import structlog

from app.engine.claim import ClaimedMonitor
from app.engine.probe import Probe

logger = structlog.get_logger()


async def _check_one(probe: Probe, url: str) -> bool:
    now = datetime.now(timezone.utc)
    monitor = ClaimedMonitor(
        id=uuid.uuid4(),
        url=url,
        method="GET",
        expected_status="2xx",
        timeout_seconds=5,
        scheduled_for=now,
        claimed_at=now,
        claim_monotonic=0.0,
    )
    try:
        result = await probe.check(monitor)
        return result.is_up
    except Exception:  # noqa: BLE001 - one canary URL's failure must never crash the round
        logger.exception("canary_probe_unexpected_error", url=url)
        return False


async def run_canary_round(
    probe: Probe, urls: Sequence[str], *, round_timeout_seconds: float = 10.0
) -> bool:
    """Probes every configured URL concurrently. Healthy (True) unless at least
    ceil(2 * len(urls) / 3) failed -- exactly "2 of 3" at the SRS's default of 3 URLs, phrased
    this way so a misconfigured count (2, 4, ...) degrades gracefully instead of raising. No
    configured URLs at all -- a dev-only override -- is trivially healthy."""
    if not urls:
        return True
    try:
        async with asyncio.timeout(round_timeout_seconds):
            outcomes = await asyncio.gather(*(_check_one(probe, url) for url in urls))
    except TimeoutError:
        logger.warning("canary_round_timeout", url_count=len(urls))
        return False

    failures = sum(1 for ok in outcomes if not ok)
    degraded_threshold = math.ceil(2 * len(urls) / 3)
    return failures < degraded_threshold


class CanaryTracker:
    """Holds the runner's current canary health and logs only on a healthy<->degraded
    transition -- mirrors FailOpenRedis's _breaker_tripped pattern in app/core/redis.py."""

    def __init__(self) -> None:
        self.ok = True

    def update(self, ok: bool) -> None:
        if ok and not self.ok:
            logger.info("canary_recovered")
        elif not ok and self.ok:
            logger.warning("canary_degraded")
        self.ok = ok
