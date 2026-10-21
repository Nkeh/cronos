"""The confirmation/re-check/incident state machine -- applies one probe result to a monitor's
counters/status and, when it crosses confirm_threshold or recovers, to its incident. Runs inside
the SAME transaction _run_one already opens for the result write (see app/engine/db_bounds.py's
bounded_transaction). CLAUDE.md non-negotiables preserved here:

- counters change only via one atomic UPDATE ... RETURNING (the `calc`/`m` CTE below)
- one open incident per subject, enforced by the DB's partial unique index, inserted with
  ON CONFLICT DO NOTHING semantics (here: a conditional INSERT ... ON CONFLICT DO UPDATE, since
  an already-open incident still needs its last_error bumped)
- the outbox row commits in the SAME transaction as the incident change (enqueue_notifications
  is called inline, before this function returns -- never from a separate transaction)
- a paused/deleted-mid-flight monitor still writes nothing, exactly as before Day 8 (the `cur`
  CTE's `WHERE is_active` guard is unchanged from results.py's original)

See docs/progress/day-08.md for the started_at design rationale (DB-anchored claimed_at +
monotonic delta, not a second round trip, not a raw wall clock).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.claim import ClaimedMonitor
from app.engine.probe import ProbeResult
from app.engine.results import write_result
from app.notifications.service import (
    IncidentSubject,
    enqueue_flapping_notification,
    enqueue_notifications,
)

# `calc`'s freshness/failure/recovery logic is expressed once and reused across every CASE --
# kept as a single bound expression (fragment) rather than retyped per-branch.
_FRESH_EXPR = "(:probe_started_at > last_state_at OR last_state_at IS NULL)"

_APPLY_SQL = text(
    f"""
    WITH cur AS (
        SELECT consecutive_failures, confirm_threshold, status, failing_since, last_state_at,
               account_id, flapping_since
        FROM monitors WHERE id = :monitor_id AND is_active
        FOR UPDATE
    ),
    calc AS (
        SELECT
            account_id, confirm_threshold, flapping_since,
            {_FRESH_EXPR} AS fresh,
            CASE WHEN NOT {_FRESH_EXPR} THEN consecutive_failures
                 WHEN :is_up THEN 0
                 ELSE consecutive_failures + 1 END AS new_consecutive_failures,
            CASE WHEN NOT {_FRESH_EXPR} THEN failing_since
                 WHEN :is_up THEN NULL
                 ELSE COALESCE(failing_since, :probe_started_at) END AS new_failing_since,
            CASE WHEN {_FRESH_EXPR} AND :is_up THEN 'up'
                 WHEN {_FRESH_EXPR} AND NOT :is_up
                      AND consecutive_failures + 1 >= confirm_threshold THEN 'down'
                 ELSE status END AS new_status,
            status AS old_status,
            CASE WHEN {_FRESH_EXPR} AND NOT :is_up
                      AND consecutive_failures = 0 AND confirm_threshold > 1
                 THEN now() + make_interval(secs => :recheck_delay_seconds) END AS recheck_candidate,
            -- True exactly at the moment the threshold is crossed, AND on every subsequent
            -- failure while still at/above it (consecutive_failures keeps growing). Combined
            -- with the EXISTS check below, this drives both "open a new incident" (first time,
            -- no conflict -> was_inserted=true) and "bump last_error on an already-open one"
            -- (every time after, conflicts -> was_inserted=false) through the same upsert.
            ({_FRESH_EXPR} AND NOT :is_up
                AND consecutive_failures + 1 >= confirm_threshold) AS threshold_just_crossed
        FROM cur
    )
    UPDATE monitors SET
        last_checked_at = now(),
        consecutive_failures = calc.new_consecutive_failures,
        failing_since = calc.new_failing_since,
        status = calc.new_status,
        status_changed_at = CASE WHEN calc.new_status IS DISTINCT FROM calc.old_status
                                  THEN now() ELSE monitors.status_changed_at END,
        next_check_at = CASE WHEN calc.recheck_candidate IS NOT NULL
                              THEN LEAST(monitors.next_check_at, calc.recheck_candidate)
                              ELSE monitors.next_check_at END,
        last_state_at = CASE WHEN calc.fresh
                              THEN GREATEST(monitors.last_state_at, :probe_started_at)
                              ELSE monitors.last_state_at END
    FROM calc WHERE monitors.id = :monitor_id
    RETURNING monitors.id, calc.account_id, calc.fresh, calc.threshold_just_crossed,
              calc.new_failing_since, calc.flapping_since
    """
)

# Issued as a separate, plain statement right after _APPLY_SQL, in the SAME transaction. Safe
# to skip re-checking is_active here: _APPLY_SQL's `cur` CTE already took FOR UPDATE on this
# monitor row, and that lock is held until the transaction commits, so nothing can pause or
# delete the monitor between the two statements within this one apply_check_result call.
_INSERT_CHECK_RESULT_SQL = text(
    """
    INSERT INTO check_results
        (monitor_id, checked_at, scheduled_for, is_up, status_code, response_time_ms, timings,
         error, error_kind, suppressed)
    VALUES
        (:monitor_id, now(), :scheduled_for, :is_up, :status_code, :response_time_ms,
         CAST(:timings AS jsonb), :error, :error_kind, false)
    """
)

_OPEN_OR_BUMP_INCIDENT_SQL = text(
    """
    INSERT INTO incidents (account_id, monitor_id, started_at, confirmed_at, cause, last_error)
    -- GREATEST, not bare now(): :started_at is the probe's own (app-derived) start time, and
    -- confirmed_at must never precede it per ck_incidents_confirmed_after_started. Root cause of
    -- the near-miss this guards against was in claim.py, not cross-host clock skew (these
    -- containers share one host clock): claimed_at was originally read via now(), which in
    -- Postgres is pinned to TRANSACTION START, not the moment that SELECT actually runs -- so on
    -- a slow claim batch, claimed_at (and everything derived from it, including started_at) could
    -- land measurably behind wall-clock reality. Fixed at the source by switching claim.py to
    -- clock_timestamp() (the instant-of-evaluation clock). GREATEST stays as a backstop, not the
    -- primary fix: :started_at is still a client-side approximation (claimed_at + a local
    -- monotonic delta, see module docstring), and this absorbs whatever sub-millisecond rounding
    -- that approximation can still carry.
    SELECT :account_id, :monitor_id, :started_at, GREATEST(now(), :started_at), :cause, :error
    WHERE :threshold_just_crossed OR EXISTS (
        SELECT 1 FROM incidents WHERE monitor_id = :monitor_id AND resolved_at IS NULL
    )
    ON CONFLICT (monitor_id) WHERE resolved_at IS NULL
    DO UPDATE SET last_error = EXCLUDED.last_error
    RETURNING id, (xmax = 0) AS was_inserted
    """
)

_RESOLVE_INCIDENT_SQL = text(
    """
    UPDATE incidents SET resolved_at = now(), resolved_reason = 'recovered'
    WHERE monitor_id = :monitor_id AND resolved_at IS NULL
    RETURNING id
    """
)

# Day 9 / FR-6.3 flapping. flapping_since itself is read (not set) by _APPLY_SQL above -- these
# three run only on the branch that just opened a BRAND NEW incident (threshold_just_crossed and
# was_inserted), never on a bump of an already-open one (which never enqueues anything either).
_FLAP_INCIDENT_COUNT_SQL = text(
    """
    SELECT count(*) FROM incidents
    WHERE monitor_id = :monitor_id
      AND started_at > now() - make_interval(mins => :window_minutes)
    """
)

_SET_FLAPPING_SINCE_SQL = text("UPDATE monitors SET flapping_since = now() WHERE id = :monitor_id")

# FR-5.4: the incident this check just opened cannot itself be acknowledged yet (nothing can
# acknowledge an incident before it exists) -- this guards the literal rule as written, not a
# scenario this code path can currently reach, in case acknowledgement ever becomes settable
# earlier in the open path.
_CURRENT_OPEN_INCIDENT_ACKED_SQL = text(
    """
    SELECT EXISTS (
        SELECT 1 FROM incidents
        WHERE monitor_id = :monitor_id AND resolved_at IS NULL AND acknowledged_at IS NOT NULL
    )
    """
)


@dataclass(frozen=True, slots=True)
class CheckOutcome:
    written: bool
    incident_opened_id: uuid.UUID | None = None
    incident_resolved_id: uuid.UUID | None = None


def _notification_payload(claimed: ClaimedMonitor, result: ProbeResult, started_at: datetime | None) -> dict:
    return {
        "subject_kind": "monitor",
        "monitor_id": str(claimed.id),
        "url": claimed.url,
        "cause": result.error_kind,
        "last_error": result.error,
        "started_at": started_at.isoformat() if started_at is not None else None,
    }


async def apply_check_result(
    session: AsyncSession,
    claimed: ClaimedMonitor,
    result: ProbeResult,
    *,
    probe_started_at: datetime,
    suppressed: bool,
    recheck_delay_seconds: int,
    flap_window_minutes: int = 30,
    flap_threshold: int = 3,
) -> CheckOutcome:
    """Applies one probe result to the state machine. Suppressed (canary-degraded) results
    write a check_results row and touch nothing else. A stale result (probe_started_at not
    after the monitor's last_state_at watermark) still writes its check_results row -- evidence
    the probe ran -- but changes no counter, status, or incident."""
    if suppressed:
        written = await write_result(session, claimed, result, suppressed=True)
        return CheckOutcome(written=written)

    db_result = await session.execute(
        _APPLY_SQL,
        {
            "monitor_id": claimed.id,
            "scheduled_for": claimed.scheduled_for,
            "is_up": result.is_up,
            "status_code": result.status_code,
            "response_time_ms": result.response_time_ms,
            "timings": json.dumps(result.timings) if result.timings is not None else None,
            "error": result.error,
            "error_kind": result.error_kind,
            "probe_started_at": probe_started_at,
            "recheck_delay_seconds": recheck_delay_seconds,
        },
    )
    row = db_result.first()
    if row is None:
        # Monitor went inactive/was deleted between claim and this write -- identical to the
        # pre-Day-8 guard, nothing written, no error.
        return CheckOutcome(written=False)

    await session.execute(
        _INSERT_CHECK_RESULT_SQL,
        {
            "monitor_id": claimed.id,
            "scheduled_for": claimed.scheduled_for,
            "is_up": result.is_up,
            "status_code": result.status_code,
            "response_time_ms": result.response_time_ms,
            "timings": json.dumps(result.timings) if result.timings is not None else None,
            "error": result.error,
            "error_kind": result.error_kind,
        },
    )

    if not row.fresh:
        # A late result against a target this monitor has already moved past (edited, or a
        # fresher result already applied). check_results row is written; state is untouched.
        return CheckOutcome(written=True)

    incident_opened_id: uuid.UUID | None = None
    incident_resolved_id: uuid.UUID | None = None

    if not result.is_up:
        incident_row = (
            await session.execute(
                _OPEN_OR_BUMP_INCIDENT_SQL,
                {
                    "account_id": row.account_id,
                    "monitor_id": claimed.id,
                    "started_at": row.new_failing_since,
                    "cause": result.error_kind,
                    "error": result.error,
                    "threshold_just_crossed": row.threshold_just_crossed,
                },
            )
        ).first()
        if incident_row is not None and incident_row.was_inserted:
            incident_opened_id = incident_row.id
            subject = IncidentSubject(kind="monitor", id=claimed.id)
            if row.flapping_since is not None:
                # Already flapping (an earlier incident in this same episode already fired the
                # one "started" notice) -- every further open/resolve cycle is silent until the
                # exit sweep (app/engine/maintenance.py) decides it's been stable long enough.
                pass
            else:
                flap_count = (
                    await session.execute(
                        _FLAP_INCIDENT_COUNT_SQL,
                        {"monitor_id": claimed.id, "window_minutes": flap_window_minutes},
                    )
                ).scalar_one()
                if flap_count >= flap_threshold:
                    await session.execute(_SET_FLAPPING_SINCE_SQL, {"monitor_id": claimed.id})
                    acked = (
                        await session.execute(
                            _CURRENT_OPEN_INCIDENT_ACKED_SQL, {"monitor_id": claimed.id}
                        )
                    ).scalar_one()
                    if not acked:
                        await enqueue_flapping_notification(
                            session, row.account_id, subject, phase="started"
                        )
                else:
                    await enqueue_notifications(
                        session,
                        row.account_id,
                        incident_opened_id,
                        subject,
                        "opened",
                        _notification_payload(claimed, result, row.new_failing_since),
                    )
    else:
        resolved_row = (
            await session.execute(_RESOLVE_INCIDENT_SQL, {"monitor_id": claimed.id})
        ).first()
        if resolved_row is not None:
            incident_resolved_id = resolved_row.id
            if row.flapping_since is None:
                await enqueue_notifications(
                    session,
                    row.account_id,
                    incident_resolved_id,
                    IncidentSubject(kind="monitor", id=claimed.id),
                    "resolved",
                    _notification_payload(claimed, result, None),
                )
            # else: flapping -- the resolved notice is suppressed too, per the brief, until the
            # exit sweep's one "ended" notice.

    return CheckOutcome(
        written=True,
        incident_opened_id=incident_opened_id,
        incident_resolved_id=incident_resolved_id,
    )
