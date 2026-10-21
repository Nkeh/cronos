"""Day 9 / FR-6.3: the flapping EXIT sweep. Entry (setting flapping_since, the one "started"
notice) happens inline in app/engine/state.py, in the same transaction as the incident that
crossed the flap threshold -- exit can't work that way, since nothing "happens" at the moment a
subject merely stays quiet for long enough. This is a periodic maintenance pass instead, run from
the runner's own tick loop (see _maybe_schedule_flapping_sweep in runner.py), under
pg_try_advisory_xact_lock so only one runner process does it at a time even when several run for
redundancy (CLAUDE.md: "Maintenance jobs run under pg_try_advisory_lock").
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.service import IncidentSubject, enqueue_flapping_notification

# hashtext() of a fixed string -- stable across processes/restarts, unlike hashing a row id.
_ADVISORY_LOCK_SQL = text("SELECT pg_try_advisory_xact_lock(hashtext('cronos_flapping_sweep'))")

# A conditional UPDATE ... RETURNING, same discipline as the heartbeat sweep (CLAUDE.md): safe to
# run twice back to back -- the second run simply finds nothing left to update, since the first
# already cleared flapping_since on every subject that qualified.
_SWEEP_MONITORS_SQL = text(
    """
    UPDATE monitors SET flapping_since = NULL
    WHERE flapping_since IS NOT NULL
      AND status = 'up'
      AND NOT EXISTS (
          SELECT 1 FROM incidents
          WHERE incidents.monitor_id = monitors.id
            AND incidents.started_at > now() - make_interval(mins => :stable_minutes)
      )
    RETURNING id, account_id
    """
)


@dataclass(frozen=True, slots=True)
class FlappingSweepResult:
    lock_acquired: bool
    monitors_cleared: int


async def run_flapping_exit_sweep(session: AsyncSession, stable_minutes: int) -> FlappingSweepResult:
    """Runs inside the caller's own bounded transaction. If the advisory lock isn't acquired
    (another runner process already holds it this instant), returns immediately -- not an error,
    just "someone else is doing this right now"."""
    acquired = (await session.execute(_ADVISORY_LOCK_SQL)).scalar_one()
    if not acquired:
        return FlappingSweepResult(lock_acquired=False, monitors_cleared=0)

    rows = (
        await session.execute(_SWEEP_MONITORS_SQL, {"stable_minutes": stable_minutes})
    ).all()
    for row in rows:
        monitor_id: uuid.UUID = row.id
        account_id: uuid.UUID = row.account_id
        await enqueue_flapping_notification(
            session, account_id, IncidentSubject(kind="monitor", id=monitor_id), phase="ended"
        )
    return FlappingSweepResult(lock_acquired=True, monitors_cleared=len(rows))
