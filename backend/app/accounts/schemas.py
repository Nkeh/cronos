from __future__ import annotations

from pydantic import BaseModel


class UsageCounts(BaseModel):
    monitors: int
    heartbeats: int
    status_pages: int
    api_keys: int


class UsageResponse(BaseModel):
    plan: str
    limits: dict[str, int | bool]
    counts: UsageCounts
    launch_period: bool
