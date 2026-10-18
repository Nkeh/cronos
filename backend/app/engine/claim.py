"""Claim due monitors under row-level locking, advancing next_check_at cadence-preservingly.

SRS Section 7: the claim and the schedule advance are one short transaction; no lock is held
during the probe. The advanced next_check_at acts as a lease -- a crash after claim just means
that one check's result is never written, never a double-check or a stuck monitor.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_CLAIM_SQL = text(
    """
    WITH due AS (
        SELECT id, next_check_at AS scheduled_for
        FROM monitors
        WHERE is_active AND next_check_at <= now()
        ORDER BY next_check_at
        LIMIT :free_slots
        FOR UPDATE SKIP LOCKED
    ),
    claimed AS (
        UPDATE monitors m
        SET next_check_at = CASE
            WHEN m.next_check_at + make_interval(secs => m.interval_seconds) > now()
                THEN m.next_check_at + make_interval(secs => m.interval_seconds)
            ELSE now() + make_interval(secs => m.interval_seconds)
        END
        FROM due
        WHERE m.id = due.id
        RETURNING m.id, m.url, m.method, m.expected_status, m.timeout_seconds, due.scheduled_for
    )
    -- clock_timestamp(), not now(): now() is pinned to this transaction's start, which can
    -- predate the moment this SELECT actually runs (and thus the moment claim_monotonic below
    -- is read) by however long the UPDATE above took. claimed_at anchors a wall-clock delta
    -- (see claim_monotonic below and app/engine/state.py's probe_started_at), so it needs the
    -- instant-of-evaluation clock, not the transaction snapshot.
    SELECT *, clock_timestamp() AS claimed_at FROM claimed
    """
)

_OLDEST_DUE_LAG_SQL = text(
    """
    SELECT COALESCE(max(extract(epoch FROM now() - next_check_at)), 0)
    FROM monitors
    WHERE is_active AND next_check_at <= now()
    """
)


@dataclass(frozen=True, slots=True)
class ClaimedMonitor:
    id: uuid.UUID
    url: str
    method: str
    expected_status: str
    timeout_seconds: int
    scheduled_for: datetime
    # Day 8: a DB-authoritative wall-clock reading from this claim batch (claimed_at, via
    # clock_timestamp() -- NOT now(), which is pinned to transaction start) plus a same-process
    # monotonic reading taken immediately after (claim_monotonic) -- together they let the
    # state machine compute an approximate, skew-free probe-start wall-clock time without an
    # extra SELECT clock_timestamp() round-trip. See app/engine/state.py and docs/progress/day-08.md.
    claimed_at: datetime
    claim_monotonic: float


async def claim_due_monitors(session: AsyncSession, free_slots: int) -> list[ClaimedMonitor]:
    """Claims up to `free_slots` due, active monitors. Returns [] if free_slots <= 0 or none
    are due -- never issues the query with a non-positive LIMIT."""
    if free_slots <= 0:
        return []
    result = await session.execute(_CLAIM_SQL, {"free_slots": free_slots})
    rows = list(result)
    claim_monotonic = time.monotonic()
    return [
        ClaimedMonitor(
            id=row.id,
            url=row.url,
            method=row.method,
            expected_status=row.expected_status,
            timeout_seconds=row.timeout_seconds,
            scheduled_for=row.scheduled_for,
            claimed_at=row.claimed_at,
            claim_monotonic=claim_monotonic,
        )
        for row in rows
    ]


async def oldest_due_lag_seconds(session: AsyncSession) -> float:
    """Age in seconds of the oldest still-due active monitor, read AFTER a claim has committed
    (reflects what's still due once this tick claimed what it could). 0 if none are due."""
    result = await session.execute(_OLDEST_DUE_LAG_SQL)
    return float(result.scalar_one())
