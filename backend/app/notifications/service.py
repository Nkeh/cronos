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

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import HeartbeatChannel, MonitorChannel, Notification, NotificationChannel


@dataclass(frozen=True, slots=True)
class IncidentSubject:
    kind: Literal["monitor", "heartbeat"]
    id: uuid.UUID


async def _routed_verified_channel_ids(
    session: AsyncSession, subject: IncidentSubject
) -> list[uuid.UUID]:
    if subject.kind == "monitor":
        join_table = MonitorChannel
        subject_col = MonitorChannel.monitor_id
    else:
        join_table = HeartbeatChannel
        subject_col = HeartbeatChannel.heartbeat_id

    return list(
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
    channel_ids = await _routed_verified_channel_ids(session, subject)
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


async def enqueue_flapping_notification(
    session: AsyncSession,
    account_id: uuid.UUID,
    subject: IncidentSubject,
    phase: Literal["started", "ended"],
) -> int:
    """Day 9 / FR-6.3: one notice per verified routed channel, replacing (not alongside) the
    normal opened/resolved fan-out while a subject is flapping. incident_id is always NULL -- a
    flapping notice describes the subject's behavior across several incidents, not any one of
    them."""
    channel_ids = await _routed_verified_channel_ids(session, subject)
    if not channel_ids:
        return 0

    session.add_all(
        Notification(
            account_id=account_id,
            incident_id=None,
            channel_id=channel_id,
            event="flapping",
            payload={"subject_kind": subject.kind, "subject_id": str(subject.id), "phase": phase},
        )
        for channel_id in channel_ids
    )
    await session.flush()
    return len(channel_ids)


async def enqueue_cap_reached_once_per_day(
    session: AsyncSession, account_id: uuid.UUID, kind: Literal["email", "webhook"]
) -> int:
    """FR-6.5: at most one cap_reached notification per account per channel kind per UTC day.
    Fanned out to every verified channel of that kind (an account with two verified email
    channels gets the one-per-day notice on both) -- the "once per day" guarantee is about the
    enqueue decision, not the recipient count. Deliberately a soft guarantee: two notifier tasks
    can both pass this check before either commits (see app/notifier -- this is the documented
    cap-overshoot tradeoff, not a bug)."""
    already_sent_today = (
        await session.execute(
            select(Notification.id)
            .join(NotificationChannel, NotificationChannel.id == Notification.channel_id)
            .where(
                Notification.account_id == account_id,
                Notification.event == "cap_reached",
                NotificationChannel.kind == kind,
                Notification.created_at
                >= text("date_trunc('day', now() AT TIME ZONE 'utc') AT TIME ZONE 'utc'"),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if already_sent_today is not None:
        return 0

    channel_ids = list(
        (
            await session.execute(
                select(NotificationChannel.id).where(
                    NotificationChannel.account_id == account_id,
                    NotificationChannel.kind == kind,
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
            incident_id=None,
            channel_id=channel_id,
            event="cap_reached",
            payload={"kind": kind},
        )
        for channel_id in channel_ids
    )
    await session.flush()
    return len(channel_ids)
