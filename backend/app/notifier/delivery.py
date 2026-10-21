"""Loads everything a delivery needs to render/send into one plain value object, read inside the
claim's own short transaction (one extra SELECT -- deliveries aren't a hot path the way probes
are). deliver_email/deliver_webhook then run with NO session at all, never mind an open
transaction, matching the runner's "no DB connection held during the actual send" discipline.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.heartbeats.models import Heartbeat
from app.incidents.models import Incident
from app.monitors.models import Monitor
from app.notifications.models import NotificationChannel
from app.notifier.claim import ClaimedNotification


@dataclass(frozen=True, slots=True)
class DeliveryContext:
    notification_id: uuid.UUID
    account_id: uuid.UUID
    event: Literal["opened", "resolved", "fail_ping", "flapping", "cap_reached"]
    payload: dict
    attempts: int

    channel_id: uuid.UUID
    channel_kind: Literal["email", "webhook"]
    channel_config: dict
    channel_secret: bytes | None  # still encrypted -- decrypted only at send time

    subject_name: str | None = None
    monitor_id: uuid.UUID | None = None
    monitor_url: str | None = None

    incident_id: uuid.UUID | None = None
    incident_cause: str | None = None
    incident_started_at: datetime | None = None
    incident_confirmed_at: datetime | None = None
    incident_resolved_at: datetime | None = None
    incident_resolved_reason: str | None = None
    incident_duration_seconds: float | None = None
    incident_last_error: str | None = None

    cap_kind: Literal["email", "webhook"] | None = None
    flap_phase: Literal["started", "ended"] | None = None


async def load_delivery_context(
    session: AsyncSession, claimed: ClaimedNotification
) -> DeliveryContext | None:
    """None means "deliver nothing, this is a permanent failure": the channel was deleted or
    de-verified since this row was enqueued, or the incident/subject it describes is gone."""
    channel = (
        await session.execute(
            select(NotificationChannel).where(NotificationChannel.id == claimed.channel_id)
        )
    ).scalar_one_or_none()
    if channel is None or channel.verified_at is None:
        return None

    base = dict(
        notification_id=claimed.id,
        account_id=claimed.account_id,
        event=claimed.event,
        payload=claimed.payload,
        attempts=claimed.attempts,
        channel_id=channel.id,
        channel_kind=channel.kind,
        channel_config=channel.config,
        channel_secret=channel.secret,
    )

    if claimed.incident_id is not None:
        row = (
            await session.execute(
                select(Incident, Monitor.name, Monitor.url, Heartbeat.name)
                .outerjoin(Monitor, Monitor.id == Incident.monitor_id)
                .outerjoin(Heartbeat, Heartbeat.id == Incident.heartbeat_id)
                .where(Incident.id == claimed.incident_id)
            )
        ).first()
        if row is None:
            return None
        incident, monitor_name, monitor_url, heartbeat_name = row
        resolved_at_or_now = incident.resolved_at or datetime.now(timezone.utc)
        return DeliveryContext(
            **base,
            subject_name=monitor_name or heartbeat_name,
            monitor_id=incident.monitor_id,
            monitor_url=monitor_url,
            incident_id=incident.id,
            incident_cause=incident.cause,
            incident_started_at=incident.started_at,
            incident_confirmed_at=incident.confirmed_at,
            incident_resolved_at=incident.resolved_at,
            incident_resolved_reason=incident.resolved_reason,
            incident_duration_seconds=(resolved_at_or_now - incident.started_at).total_seconds(),
            incident_last_error=incident.last_error,
        )

    if claimed.event == "flapping":
        subject_kind = claimed.payload.get("subject_kind")
        subject_id = uuid.UUID(claimed.payload["subject_id"])
        if subject_kind == "monitor":
            name = (
                await session.execute(select(Monitor.name).where(Monitor.id == subject_id))
            ).scalar_one_or_none()
        else:
            name = (
                await session.execute(select(Heartbeat.name).where(Heartbeat.id == subject_id))
            ).scalar_one_or_none()
        if name is None:
            return None
        return DeliveryContext(
            **base,
            subject_name=name,
            monitor_id=subject_id if subject_kind == "monitor" else None,
            flap_phase=claimed.payload.get("phase"),
        )

    if claimed.event == "cap_reached":
        return DeliveryContext(**base, cap_kind=claimed.payload.get("kind"))

    return None
