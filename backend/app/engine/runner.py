"""`python -m app.engine.runner` — ticks every 2s. No DB writes yet (Day 6 adds claim/probe)."""

from __future__ import annotations

import asyncio
import pathlib

from app.core.config import get_settings
from app.core.db import wait_for_database
from app.core.logging import configure_logging
from app.core.tick_loop import run_tick_loop

TICK_SECONDS = 2
LOG_EVERY_N_TICKS = 30
ALIVE_FILE = pathlib.Path("/tmp/alive")


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.check_production_guard()

    await wait_for_database(settings.database_url)

    async def on_tick(tick: int) -> None:
        # Day 6 drops claim/probe/incident logic in here, once per tick.
        return None

    await run_tick_loop(
        name="runner",
        interval_seconds=TICK_SECONDS,
        log_every=LOG_EVERY_N_TICKS,
        alive_file=ALIVE_FILE,
        on_tick=on_tick,
    )


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
