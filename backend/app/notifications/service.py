"""Outbox enqueue only -- Day 8 writes rows, Day 9 drains and delivers them.

enqueue_notifications is called from app/engine/state.py (incident opened/resolved) in the SAME
transaction as the incident change -- never from a separate transaction, never inline-sent. With
no verified, routed channels it inserts nothing (not an error): an account that hasn't set up
alerting yet still gets incidents recorded, just nothing queued to send.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import HeartbeatChannel, MonitorChannel, Notification, NotificationChannel


@dataclass(frozen=True, slots=True)
class IncidentSubject:
    kind: Literal["monitor", "heartbeat"]
    id: uuid.UUID


async def enqueue_notifications(
    session: AsyncSession,
    account_id: uuid.UUID,
    incident_id: uuid.UUID,
    subject: IncidentSubject,
    event: Literal["opened", "resolved"],
    payload: dict,
) -> int:
    """Fan out one outbox row per verified channel routed to `subject`. Returns the number of
    rows inserted (0 if nothing is routed yet, or every routed channel is unverified)."""
    if subject.kind == "monitor":
        join_table = MonitorChannel
        subject_col = MonitorChannel.monitor_id
    else:
        join_table = HeartbeatChannel
        subject_col = HeartbeatChannel.heartbeat_id

    channel_ids = (
        (
            await session.execute(
                select(NotificationChannel.id)
                .join(join_table, join_table.channel_id == NotificationChannel.id)
                .where(
                    subject_col == subject.id,
                    NotificationChannel.verified_at.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if not channel_ids:
        return 0

    session.add_all(
        Notification(
            account_id=account_id,
            incident_id=incident_id,
            channel_id=channel_id,
            event=event,
            payload=payload,
        )
        for channel_id in channel_ids
    )
    await session.flush()
    return len(channel_ids)
