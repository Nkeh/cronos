"""Write a probe result in one short transaction -- paused/deleted mid-flight writes nothing.

CLAUDE.md non-negotiable: result write is a CTE that updates monitors.last_checked_at ONLY IF
the monitor still exists and is_active, and inserts the CheckResult from that same CTE -- if
the monitor was paused or deleted between claim and probe completion, zero rows are written,
no error.
"""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.claim import ClaimedMonitor
from app.engine.probe import ProbeResult

_WRITE_RESULT_SQL = text(
    """
    WITH m AS (
        UPDATE monitors
        SET last_checked_at = now()
        WHERE id = :monitor_id AND is_active
        RETURNING id
    )
    INSERT INTO check_results
        (monitor_id, checked_at, scheduled_for, is_up, status_code, response_time_ms, timings,
         error)
    SELECT :monitor_id, now(), :scheduled_for, :is_up, :status_code, :response_time_ms,
           CAST(:timings AS jsonb), :error
    FROM m
    RETURNING id
    """
)


async def write_result(
    session: AsyncSession, claimed: ClaimedMonitor, result: ProbeResult
) -> bool:
    """Returns True if a check_results row was actually written (the monitor was still
    active), False if the monitor was paused/deleted mid-flight (nothing written, no error)."""
    db_result = await session.execute(
        _WRITE_RESULT_SQL,
        {
            "monitor_id": claimed.id,
            "scheduled_for": claimed.scheduled_for,
            "is_up": result.is_up,
            "status_code": result.status_code,
            "response_time_ms": result.response_time_ms,
            "timings": json.dumps(result.timings) if result.timings is not None else None,
            "error": result.error,
        },
    )
    return db_result.first() is not None
