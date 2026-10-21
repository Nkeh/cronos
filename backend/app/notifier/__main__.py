"""`python -m app.notifier` -- ticks every 1s, drains the Day 8 outbox: claims due/expired-lease
notification rows with SKIP LOCKED, delivers email or a signed webhook with NO DB connection held
during the send, then records the outcome in its own short transaction. Same tick-loop/semaphore/
deadline/DB-outage-backoff shape as app/engine/runner.py -- see that module and
docs/progress/day-09.md for the shared design.

At-least-once, by design: an expired lease (the notifier died mid-delivery) gets reclaimed and
redelivered. A receiver sees the same X-Cronos-Delivery (the notification id) twice in that case
-- this is documented, not a bug, and is why the signing header exists independent of delivery
count.
"""

from __future__ import annotations

import asyncio
import pathlib
import time

import structlog
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.core.config import Settings, get_settings
from app.core.db import wait_for_database
from app.core.logging import configure_logging
from app.core.tick_loop import run_tick_loop
# Side-effect only: same fix as app/engine/runner.py (see its comment for the full story) --
# this process never otherwise imports app.accounts.models, so the first ORM flush of a
# Notification row (enqueue_cap_reached_once_per_day below, or any NotificationAttempt insert in
# record_outcome) would raise NoReferencedTableError resolving Notification.account_id's FK.
from app.db import models as _all_models  # noqa: F401
from app.engine.db_bounds import bounded_transaction
from app.notifier.caps import is_over_cap
from app.notifier.claim import ClaimedNotification, claim_due_notifications
from app.notifier.context import NotifierContext
from app.notifier.delivery import DeliveryContext, load_delivery_context
from app.notifier.email import deliver_email
from app.notifier.outcomes import DeliveryOutcome
from app.notifier.record import record_outcome
from app.notifier.webhook import deliver_webhook
from app.notifications.service import enqueue_cap_reached_once_per_day

TICK_SECONDS = 1
LOG_EVERY_N_TICKS = 30
ALIVE_FILE = pathlib.Path("/tmp/alive")

_DB_UNAVAILABLE_ERRORS = (DBAPIError, OSError)
_NOTIFIER_TXN_ERRORS = (DBAPIError, OSError, PoolTimeoutError)

logger = structlog.get_logger()


async def _load_and_cap_check(
    ctx: NotifierContext, claimed: ClaimedNotification
) -> tuple[DeliveryContext | None, bool]:
    """Runs in one bounded transaction: load the delivery context, and -- only if there's a real
    channel to send through -- decide whether today's cap is already hit for that channel kind,
    enqueueing the one-per-day cap_reached notice if this is the send that tips it over. Returns
    (context_or_None, over_cap)."""
    async with ctx.session_factory() as session:
        async with bounded_transaction(
            session,
            lock_timeout_ms=ctx.settings.notifier_claim_lock_timeout_ms,
            statement_timeout_ms=ctx.settings.notifier_claim_statement_timeout_ms,
        ):
            delivery_ctx = await load_delivery_context(session, claimed)
            if delivery_ctx is None:
                return None, False
            over_cap = await is_over_cap(session, claimed.account_id, delivery_ctx.channel_kind)
            if over_cap:
                await enqueue_cap_reached_once_per_day(
                    session, claimed.account_id, delivery_ctx.channel_kind
                )
            return delivery_ctx, over_cap


async def _send(ctx: NotifierContext, delivery_ctx: DeliveryContext) -> DeliveryOutcome:
    if delivery_ctx.channel_kind == "email":
        return await deliver_email(ctx.settings, delivery_ctx)
    return await deliver_webhook(ctx.settings, delivery_ctx)


async def _run_one(ctx: NotifierContext, claimed: ClaimedNotification) -> None:
    deadline_seconds = ctx.settings.webhook_timeout_seconds + ctx.settings.notifier_task_margin_seconds
    try:
        async with asyncio.timeout(deadline_seconds):
            delivery_ctx, over_cap = await _load_and_cap_check(ctx, claimed)

            if delivery_ctx is None:
                outcome = DeliveryOutcome(outcome="failed", error="channel missing or unverified")
                duration_ms = 0
            elif over_cap:
                outcome = DeliveryOutcome(outcome="suppressed")
                duration_ms = 0
            else:
                async with ctx.semaphore:
                    start = time.monotonic()
                    outcome = await _send(ctx, delivery_ctx)
                    duration_ms = round((time.monotonic() - start) * 1000)

            async with ctx.session_factory() as session:
                async with bounded_transaction(
                    session,
                    lock_timeout_ms=ctx.settings.notifier_claim_lock_timeout_ms,
                    statement_timeout_ms=ctx.settings.notifier_claim_statement_timeout_ms,
                ):
                    await record_outcome(session, claimed, outcome, ctx.settings, duration_ms)
    except TimeoutError:
        logger.warning(
            "notification_task_abandoned_deadline",
            notification_id=str(claimed.id),
            deadline_seconds=deadline_seconds,
        )
    except PoolTimeoutError:
        logger.warning("notification_record_pool_timeout", notification_id=str(claimed.id))
    except _DB_UNAVAILABLE_ERRORS as exc:
        logger.warning(
            "notification_record_db_unavailable", notification_id=str(claimed.id), error=str(exc)
        )
    except Exception:  # noqa: BLE001 - one notification's task must never crash the notifier
        logger.exception("notification_task_unexpected_error", notification_id=str(claimed.id))


def _spawn(ctx: NotifierContext, claimed: ClaimedNotification) -> None:
    task = asyncio.create_task(_run_one(ctx, claimed))
    ctx.in_flight_tasks.add(task)
    task.add_done_callback(ctx.in_flight_tasks.discard)


async def _claim_tick(ctx: NotifierContext) -> list[ClaimedNotification]:
    free_slots = ctx.settings.notifier_concurrency - len(ctx.in_flight_tasks)
    try:
        async with ctx.session_factory() as session:
            async with bounded_transaction(
                session,
                lock_timeout_ms=ctx.settings.notifier_claim_lock_timeout_ms,
                statement_timeout_ms=ctx.settings.notifier_claim_statement_timeout_ms,
            ):
                return await claim_due_notifications(
                    session, free_slots, ctx.settings.notifier_lease_seconds
                )
    except _NOTIFIER_TXN_ERRORS as exc:
        logger.warning("notifier_claim_failed", error=str(exc))
        ctx.consecutive_db_failures += 1
        return []


async def on_tick(ctx: NotifierContext) -> None:
    failures_before = ctx.consecutive_db_failures

    claimed = await _claim_tick(ctx)
    for notification in claimed:
        _spawn(ctx, notification)

    if ctx.consecutive_db_failures > failures_before:
        backoff_seconds = min(2**ctx.consecutive_db_failures, 10)
        logger.warning(
            "notifier_db_backoff",
            consecutive_failures=ctx.consecutive_db_failures,
            backoff_seconds=backoff_seconds,
        )
        await asyncio.sleep(backoff_seconds)
    else:
        ctx.consecutive_db_failures = 0


async def run(*, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    settings.check_production_guard()

    await wait_for_database(settings.database_url)

    ctx = NotifierContext(settings=settings)

    async def _on_tick(_tick: int) -> None:
        await on_tick(ctx)

    try:
        await run_tick_loop(
            name="notifier",
            interval_seconds=TICK_SECONDS,
            log_every=LOG_EVERY_N_TICKS,
            alive_file=ALIVE_FILE,
            on_tick=_on_tick,
        )
    finally:
        if ctx.in_flight_tasks:
            done, pending = await asyncio.wait(
                ctx.in_flight_tasks, timeout=settings.notifier_drain_seconds
            )
            logger.info("notifier_drain_complete", finished=len(done), abandoned=len(pending))
        else:
            logger.info("notifier_drain_complete", finished=0, abandoned=0)
        await ctx.engine.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
