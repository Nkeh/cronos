"""Incident request/response schemas. Subject is polymorphic (monitor | heartbeat) even though
only monitor incidents exist before Day 10 -- the DB model (app/incidents/models.py) has always
supported both, so the API shape matches it from day one rather than needing rework later."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class IncidentSubjectPublic(BaseModel):
    type: Literal["monitor", "heartbeat"]
    id: uuid.UUID
    name: str | None


class IncidentPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject: IncidentSubjectPublic
    cause: str
    last_error: str | None
    started_at: datetime
    confirmed_at: datetime | None
    resolved_at: datetime | None
    resolved_reason: str | None
    acknowledged_at: datetime | None
    duration_seconds: float


class IncidentListResponse(BaseModel):
    items: list[IncidentPublic]
    next_cursor: str | None


class CheckResultSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    is_up: bool
    status_code: int | None
    error_kind: str | None
    response_time_ms: int | None
    checked_at: datetime
    suppressed: bool


class IncidentDetail(IncidentPublic):
    timeline: list[CheckResultSummary]


class OpenIncidentCount(BaseModel):
    count: int
