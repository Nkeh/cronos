"""Claim due outbox rows under row-level locking, same SKIP LOCKED shape as
app/engine/claim.py's claim_due_monitors.

The WHERE clause's 'sending' branch is what reclaims an expired lease: a row stuck in 'sending'
past its own next_attempt_at (the notifier process died mid-delivery) looks exactly like a fresh
'pending' row to this query and gets claimed again, attempts incremented again -- this is the
documented at-least-once behavior (the same notification id, sent as the webhook
X-Cronos-Delivery header, can go out twice).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_CLAIM_SQL = text(
    """
    WITH due AS (
        SELECT id FROM notifications
        WHERE (status = 'pending' AND next_attempt_at <= now())
           OR (status = 'sending' AND next_attempt_at <= now())
        ORDER BY next_attempt_at
        LIMIT :free_slots
        FOR UPDATE SKIP LOCKED
    )
    UPDATE notifications n
    SET status = 'sending', attempts = attempts + 1,
        next_attempt_at = clock_timestamp() + make_interval(secs => :lease_seconds)
    FROM due
    WHERE n.id = due.id
    RETURNING n.id, n.account_id, n.incident_id, n.channel_id, n.event, n.payload, n.attempts
    """
)


@dataclass(frozen=True, slots=True)
class ClaimedNotification:
    id: uuid.UUID
    account_id: uuid.UUID
    incident_id: uuid.UUID | None
    channel_id: uuid.UUID
    event: Literal["opened", "resolved", "fail_ping", "flapping", "cap_reached"]
    payload: dict
    attempts: int


async def claim_due_notifications(
    session: AsyncSession, free_slots: int, lease_seconds: int
) -> list[ClaimedNotification]:
    """Claims up to `free_slots` due/expired-lease rows. Returns [] if free_slots <= 0 -- never
    issues the query with a non-positive LIMIT."""
    if free_slots <= 0:
        return []
    result = await session.execute(
        _CLAIM_SQL, {"free_slots": free_slots, "lease_seconds": lease_seconds}
    )
    return [
        ClaimedNotification(
            id=row.id,
            account_id=row.account_id,
            incident_id=row.incident_id,
            channel_id=row.channel_id,
            event=row.event,
            payload=row.payload,
            attempts=row.attempts,
        )
        for row in result
    ]


async def oldest_pending_age_seconds(session: AsyncSession) -> float | None:
    """None if nothing is pending -- used by /readyz's advisory outbox-age check."""
    result = await session.execute(
        text(
            "SELECT extract(epoch FROM now() - min(created_at)) "
            "FROM notifications WHERE status = 'pending'"
        )
    )
    value = result.scalar_one()
    return float(value) if value is not None else None
