"""The shared tick-loop shape for the runner and the notifier.

Both processes tick forever until SIGTERM/SIGINT, finish the in-flight tick,
then return. Day 6 (runner: claim/probe/incidents) and Day 9 (notifier: drain
the outbox) drop their real logic into `on_tick` without touching this loop.
"""

from __future__ import annotations

import asyncio
import pathlib
import signal
from collections.abc import Awaitable, Callable

import structlog

logger = structlog.get_logger()

OnTick = Callable[[int], Awaitable[None]]


async def run_tick_loop(
    *,
    name: str,
    interval_seconds: float,
    log_every: int,
    alive_file: pathlib.Path,
    on_tick: OnTick | None = None,
) -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    tick = 0
    logger.info(f"{name}_started", interval_seconds=interval_seconds)
    while not stop_event.is_set():
        tick += 1
        alive_file.write_text(str(tick))

        log = logger.info if tick % log_every == 0 else logger.debug
        log(f"{name}_tick", tick=tick)

        if on_tick is not None:
            await on_tick(tick)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            pass

    logger.info(f"{name}_shutdown_complete")
