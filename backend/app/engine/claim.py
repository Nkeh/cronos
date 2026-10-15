"""Claim due monitors under row-level locking, advancing next_check_at cadence-preservingly.

SRS Section 7: the claim and the schedule advance are one short transaction; no lock is held
during the probe. The advanced next_check_at acts as a lease -- a crash after claim just means
that one check's result is never written, never a double-check or a stuck monitor.
"""

from __future__ import annotations

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
    SELECT * FROM claimed
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


async def claim_due_monitors(session: AsyncSession, free_slots: int) -> list[ClaimedMonitor]:
    """Claims up to `free_slots` due, active monitors. Returns [] if free_slots <= 0 or none
    are due -- never issues the query with a non-positive LIMIT."""
    if free_slots <= 0:
        return []
    result = await session.execute(_CLAIM_SQL, {"free_slots": free_slots})
    return [
        ClaimedMonitor(
            id=row.id,
            url=row.url,
            method=row.method,
            expected_status=row.expected_status,
            timeout_seconds=row.timeout_seconds,
            scheduled_for=row.scheduled_for,
        )
        for row in result
    ]


async def oldest_due_lag_seconds(session: AsyncSession) -> float:
    """Age in seconds of the oldest still-due active monitor, read AFTER a claim has committed
    (reflects what's still due once this tick claimed what it could). 0 if none are due."""
    result = await session.execute(_OLDEST_DUE_LAG_SQL)
    return float(result.scalar_one())
