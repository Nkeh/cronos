"""Incidents: /api/v1/incidents. Tenant isolation and scope-dependency patterns copied verbatim
from app/monitors/router.py (cross-account lookups always 404, never 403). This is the first
cursor-paginated endpoint in the codebase -- no existing pattern to copy, so one is established
here: an opaque cursor over the keyset (started_at DESC, id DESC), matching the existing
ix_incidents_account_id_started_at index shape.
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AuthContext, require_scope, require_verified
from app.auth.models import User
from app.core.db import get_db_session
from app.core.errors import ApiError
from app.heartbeats.models import Heartbeat
from app.incidents.models import Incident
from app.incidents.schemas import (
    CheckResultSummary,
    IncidentDetail,
    IncidentListResponse,
    IncidentPublic,
    IncidentSubjectPublic,
    OpenIncidentCount,
)
from app.monitors.models import CheckResult, Monitor

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])

_MAX_LIMIT = 100
_TIMELINE_LIMIT = 200

_DURATION_SECONDS_EXPR = func.extract(
    "epoch", func.coalesce(Incident.resolved_at, func.now()) - Incident.started_at
)


def _encode_cursor(started_at: datetime, incident_id: uuid.UUID) -> str:
    raw = f"{started_at.isoformat()}|{incident_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        started_at_str, id_str = raw.split("|", 1)
        return datetime.fromisoformat(started_at_str), uuid.UUID(id_str)
    except Exception:
        raise ApiError(422, "invalid_cursor", "Malformed cursor.", field="cursor") from None


def _to_public(
    incident: Incident, monitor_name: str | None, heartbeat_name: str | None, duration_seconds: float
) -> IncidentPublic:
    if incident.monitor_id is not None:
        subject = IncidentSubjectPublic(type="monitor", id=incident.monitor_id, name=monitor_name)
    else:
        subject = IncidentSubjectPublic(
            type="heartbeat", id=incident.heartbeat_id, name=heartbeat_name
        )
    return IncidentPublic(
        id=incident.id,
        subject=subject,
        cause=incident.cause,
        last_error=incident.last_error,
        started_at=incident.started_at,
        confirmed_at=incident.confirmed_at,
        resolved_at=incident.resolved_at,
        resolved_reason=incident.resolved_reason,
        acknowledged_at=incident.acknowledged_at,
        duration_seconds=duration_seconds,
    )


async def _get_owned_incident(db: AsyncSession, account_id: uuid.UUID, incident_id: uuid.UUID) -> Incident:
    incident = (
        await db.execute(
            select(Incident).where(Incident.account_id == account_id, Incident.id == incident_id)
        )
    ).scalar_one_or_none()
    if incident is None:
        raise ApiError(404, "not_found", "Incident not found.")
    return incident


@router.get("", response_model=IncidentListResponse)
async def list_incidents(
    state: Literal["open", "resolved"] | None = None,
    monitor_id: uuid.UUID | None = None,
    cursor: str | None = None,
    limit: int = Query(default=25, ge=1, le=_MAX_LIMIT),
    principal: AuthContext = Depends(require_scope("incidents:read")),
    db: AsyncSession = Depends(get_db_session),
) -> IncidentListResponse:
    conditions = [Incident.account_id == principal.user.account_id]
    if state == "open":
        conditions.append(Incident.resolved_at.is_(None))
    elif state == "resolved":
        conditions.append(Incident.resolved_at.is_not(None))
    if monitor_id is not None:
        conditions.append(Incident.monitor_id == monitor_id)
    if cursor is not None:
        cursor_started_at, cursor_id = _decode_cursor(cursor)
        conditions.append(
            tuple_(Incident.started_at, Incident.id) < tuple_(cursor_started_at, cursor_id)
        )

    rows = (
        await db.execute(
            select(Incident, Monitor.name, Heartbeat.name, _DURATION_SECONDS_EXPR)
            .outerjoin(Monitor, Monitor.id == Incident.monitor_id)
            .outerjoin(Heartbeat, Heartbeat.id == Incident.heartbeat_id)
            .where(*conditions)
            .order_by(Incident.started_at.desc(), Incident.id.desc())
            .limit(limit)
        )
    ).all()

    items = [
        _to_public(incident, monitor_name, heartbeat_name, duration_seconds)
        for incident, monitor_name, heartbeat_name, duration_seconds in rows
    ]
    next_cursor = (
        _encode_cursor(rows[-1][0].started_at, rows[-1][0].id) if len(rows) == limit else None
    )
    return IncidentListResponse(items=items, next_cursor=next_cursor)


@router.get("/open-count", response_model=OpenIncidentCount)
async def open_incident_count(
    principal: AuthContext = Depends(require_scope("incidents:read")),
    db: AsyncSession = Depends(get_db_session),
) -> OpenIncidentCount:
    count = (
        await db.execute(
            select(func.count())
            .select_from(Incident)
            .where(
                Incident.account_id == principal.user.account_id,
                Incident.resolved_at.is_(None),
            )
        )
    ).scalar_one()
    return OpenIncidentCount(count=count)


@router.get("/{incident_id}", response_model=IncidentDetail)
async def get_incident(
    incident_id: uuid.UUID,
    principal: AuthContext = Depends(require_scope("incidents:read")),
    db: AsyncSession = Depends(get_db_session),
) -> IncidentDetail:
    incident = await _get_owned_incident(db, principal.user.account_id, incident_id)

    monitor_name = heartbeat_name = None
    timeline: list[CheckResultSummary] = []
    if incident.monitor_id is not None:
        monitor_name = (
            await db.execute(select(Monitor.name).where(Monitor.id == incident.monitor_id))
        ).scalar_one_or_none()
        timeline_rows = (
            await db.execute(
                select(CheckResult)
                .where(
                    CheckResult.monitor_id == incident.monitor_id,
                    CheckResult.checked_at >= incident.started_at,
                )
                .order_by(CheckResult.checked_at.desc())
                .limit(_TIMELINE_LIMIT)
            )
        ).scalars().all()
        timeline = [CheckResultSummary.model_validate(row) for row in timeline_rows]
    else:
        heartbeat_name = (
            await db.execute(select(Heartbeat.name).where(Heartbeat.id == incident.heartbeat_id))
        ).scalar_one_or_none()

    duration_seconds = (
        await db.execute(select(_DURATION_SECONDS_EXPR).where(Incident.id == incident.id))
    ).scalar_one()

    public = _to_public(incident, monitor_name, heartbeat_name, duration_seconds)
    return IncidentDetail(**public.model_dump(), timeline=timeline)


@router.post("/{incident_id}/ack", response_model=IncidentPublic)
async def ack_incident(
    incident_id: uuid.UUID,
    user: User = Depends(require_verified),
    _scope: AuthContext = Depends(require_scope("incidents:write")),
    db: AsyncSession = Depends(get_db_session),
) -> IncidentPublic:
    incident = await _get_owned_incident(db, user.account_id, incident_id)
    if incident.resolved_at is not None:
        raise ApiError(409, "incident_resolved", "Cannot acknowledge a resolved incident.")

    if incident.acknowledged_at is None:
        await db.execute(
            update(Incident)
            .where(Incident.id == incident.id)
            .values(acknowledged_at=func.now(), acknowledged_by=user.id)
        )
        await db.commit()
        await db.refresh(incident)

    monitor_name = heartbeat_name = None
    if incident.monitor_id is not None:
        monitor_name = (
            await db.execute(select(Monitor.name).where(Monitor.id == incident.monitor_id))
        ).scalar_one_or_none()
    else:
        heartbeat_name = (
            await db.execute(select(Heartbeat.name).where(Heartbeat.id == incident.heartbeat_id))
        ).scalar_one_or_none()
    duration_seconds = (
        await db.execute(select(_DURATION_SECONDS_EXPR).where(Incident.id == incident.id))
    ).scalar_one()
    return _to_public(incident, monitor_name, heartbeat_name, duration_seconds)
