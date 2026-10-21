"""Channels API request/response schemas.

`config`'s shape depends on `kind` (email -> {"address"}, webhook -> {"url"}) -- kept as a plain
dict here and validated imperatively in the router (same reasoning as monitors/schemas.py's
module docstring: schema-level checks catch shape typos cheaply, but the webhook URL's real
validation is the stateful ssrf_policy sequence, which can't live in a Pydantic validator).
`secret` is never a field on any response schema here -- see app/notifications/router.py's
module docstring for the two explicit endpoints that exist specifically to surface it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ChannelCreate(BaseModel):
    kind: Literal["email", "webhook"]
    name: str = Field(min_length=1, max_length=60)
    config: dict = Field(default_factory=dict)
    is_default: bool = False


class ChannelPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    is_default: bool | None = None
    config: dict | None = None


class ChannelPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    name: str
    config: dict
    is_default: bool
    verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ChannelSecretResponse(BaseModel):
    secret: str


class ChannelVerifyEmailRequest(BaseModel):
    token: str


class ChannelTestResponse(BaseModel):
    ok: bool
    status_code: int | None = None
    error: str | None = None


class MonitorChannelsResponse(BaseModel):
    channel_ids: list[uuid.UUID]


class MonitorChannelsUpdate(BaseModel):
    channel_ids: list[uuid.UUID]


class DeliveryAttemptPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    attempted_at: datetime
    outcome: str
    status_code: int | None
    error: str | None
    duration_ms: int


class DeliveryPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event: str
    status: str
    attempts: int
    created_at: datetime
    sent_at: datetime | None
    last_error: str | None
    recent_attempts: list[DeliveryAttemptPublic] = []


class DeliveryListResponse(BaseModel):
    items: list[DeliveryPublic]
    next_cursor: str | None
