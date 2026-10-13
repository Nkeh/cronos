"""GET /api/v1/usage — plan limits and current counts.

Open to any authenticated principal (session or API key), no verification or
scope requirement: reading your own usage isn't gated behind anything. Counts
only; daily usage rollups are Day 15.
"""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.accounts.models import Account
from app.accounts.schemas import UsageCounts, UsageResponse
from app.auth.dependencies import current_user
from app.auth.models import ApiKey, User
from app.core.db import get_db_session
from app.heartbeats.models import Heartbeat
from app.monitors.models import Monitor
from app.plans.config import get_plan
from app.status_pages.models import StatusPage

router = APIRouter(prefix="/api/v1", tags=["accounts"])


async def _count(
    db: AsyncSession,
    model: type[Any],
    account_id: uuid.UUID,
    extra_filter: ColumnElement[bool] | None = None,
) -> int:
    stmt = select(func.count()).select_from(model).where(model.account_id == account_id)
    if extra_filter is not None:
        stmt = stmt.where(extra_filter)
    return (await db.execute(stmt)).scalar_one()


@router.get("/usage", response_model=UsageResponse)
async def get_usage(
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db_session)
) -> UsageResponse:
    account = await db.get(Account, user.account_id)
    assert account is not None
    plan = get_plan(account.plan)

    counts = UsageCounts(
        monitors=await _count(db, Monitor, account.id),
        heartbeats=await _count(db, Heartbeat, account.id),
        status_pages=await _count(db, StatusPage, account.id),
        api_keys=await _count(db, ApiKey, account.id, ApiKey.revoked_at.is_(None)),
    )

    limits = {k: v for k, v in dataclasses.asdict(plan).items() if k != "name"}

    return UsageResponse(plan=plan.name, limits=limits, counts=counts, launch_period=True)
