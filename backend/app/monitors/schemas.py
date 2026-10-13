"""Monitor request/response schemas.

MonitorCreate/MonitorPatch mirror every DB CHECK constraint a client could
plausibly trip (expected_status format, interval/timeout/confirm_threshold
ranges, timeout < interval) so ordinary bad input gets a clean 422, not an
uncaught IntegrityError surfacing as a 500. The plan's own interval minimum
(120s, account-dependent) is enforced separately in the router via
check_interval_minimum, since it depends on the account's plan, not a static
schema constraint.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_EXPECTED_STATUS_PATTERN = r"^(2xx|[1-5][0-9]{2})$"


class MonitorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: str
    method: Literal["GET", "HEAD"] = "GET"
    expected_status: str = Field(default="2xx", pattern=_EXPECTED_STATUS_PATTERN)
    interval_seconds: int = Field(default=300, ge=30)
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    confirm_threshold: int = Field(default=2, ge=1, le=10)

    @model_validator(mode="after")
    def _timeout_below_interval(self) -> MonitorCreate:
        if self.timeout_seconds >= self.interval_seconds:
            raise ValueError("timeout_seconds must be less than interval_seconds")
        return self


class MonitorPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    url: str | None = None
    method: Literal["GET", "HEAD"] | None = None
    expected_status: str | None = Field(default=None, pattern=_EXPECTED_STATUS_PATTERN)
    interval_seconds: int | None = Field(default=None, ge=30)
    timeout_seconds: int | None = Field(default=None, ge=1, le=60)
    confirm_threshold: int | None = Field(default=None, ge=1, le=10)

    @model_validator(mode="after")
    def _timeout_below_interval(self) -> MonitorPatch:
        # Only catches the case where BOTH fields are in the same PATCH — the
        # router separately re-checks the merged (post-patch) values, since a
        # PATCH touching only one of the two can still conflict with the
        # monitor's existing stored value for the other.
        if (
            self.timeout_seconds is not None
            and self.interval_seconds is not None
            and self.timeout_seconds >= self.interval_seconds
        ):
            raise ValueError("timeout_seconds must be less than interval_seconds")
        return self


class MonitorPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    url: str
    method: str
    expected_status: str
    interval_seconds: int
    timeout_seconds: int
    confirm_threshold: int
    status: str
    is_active: bool
    next_check_at: datetime
    last_checked_at: datetime | None
    status_changed_at: datetime
    created_at: datetime
    updated_at: datetime
