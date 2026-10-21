"""_NotifierContext -- the notifier's equivalent of app/engine/runner.py's _RunnerContext. Same
shape deliberately: a plain mutable object (not a dataclass, every field mutated in place from
on_tick/_run_one closures), own engine/session_factory, own semaphore, own in_flight_tasks set.
"""

from __future__ import annotations

import asyncio

from app.core.config import Settings
from app.core.db import create_engine, create_session_factory


class NotifierContext:
    def __init__(self, *, settings: Settings) -> None:
        self.settings = settings
        self.engine = create_engine(
            settings,
            pool_size=settings.notifier_pool_size,
            max_overflow=settings.notifier_max_overflow,
            pool_timeout=settings.notifier_pool_timeout_seconds,
        )
        self.session_factory = create_session_factory(self.engine)
        self.semaphore = asyncio.Semaphore(settings.notifier_concurrency)
        self.in_flight_tasks: set[asyncio.Task[None]] = set()
        self.consecutive_db_failures = 0
