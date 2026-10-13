"""apply_plan_limits — the SRS Section 12 downgrade rule.

The SRS's own downgrade-rule text describes the v1->v2 launch->free
transition specifically and labels it "planned, not built" for v1.
CLAUDE.md nonetheless requires this implemented and tested now, just not
wired to any endpoint — this module is that function, ready for whenever v2
calls it.

Nothing is deleted. Monitors/heartbeats above their plan max are paused,
newest first; intervals/periods below the plan minimum are raised to it;
status pages beyond the plan's max that are currently public are unpublished
(is_public=False) — which, per the status_pages.access_token_required CHECK,
means generating an access_token_hash for any of them that doesn't already
have one, since a private page is required to have one. Day 11 (status
pages) should treat that generated hash as needing a real token issued to
the account owner if this path is ever wired up to run live.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_token, new_raw_token
from app.heartbeats.models import Heartbeat
from app.monitors.models import Monitor
from app.plans.config import PlanLimits
from app.status_pages.models import StatusPage


@dataclass(frozen=True)
class DowngradeReport:
    paused_monitor_ids: list[uuid.UUID] = field(default_factory=list)
    paused_heartbeat_ids: list[uuid.UUID] = field(default_factory=list)
    raised_interval_monitor_ids: list[uuid.UUID] = field(default_factory=list)
    raised_period_heartbeat_ids: list[uuid.UUID] = field(default_factory=list)
    unpublished_status_page_ids: list[uuid.UUID] = field(default_factory=list)


async def _pause_surplus(
    db: AsyncSession, model: type[Monitor] | type[Heartbeat], account_id: uuid.UUID, max_count: int
) -> list[uuid.UUID]:
    # Ascending by created_at: the oldest max_count rows (the ones to KEEP
    # active) sort first; everything after them is the newest surplus, the
    # part to pause. (Sorting descending and slicing [max_count:] would keep
    # the newest and pause the oldest — backwards from "newest first".)
    rows = (
        (
            await db.execute(
                select(model)
                .where(model.account_id == account_id, model.is_active.is_(True))
                .order_by(model.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    surplus = rows[max_count:] if max_count >= 0 else []
    for row in surplus:
        row.is_active = False
        row.status = "paused"
    return [row.id for row in surplus]


async def _raise_floor(
    db: AsyncSession,
    model: type[Monitor] | type[Heartbeat],
    account_id: uuid.UUID,
    column_name: str,
    minimum: int,
) -> list[uuid.UUID]:
    rows = (
        (
            await db.execute(
                select(model).where(
                    model.account_id == account_id,
                    getattr(model, column_name) < minimum,
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        setattr(row, column_name, minimum)
    return [row.id for row in rows]


async def _unpublish_surplus(
    db: AsyncSession, account_id: uuid.UUID, max_count: int
) -> list[uuid.UUID]:
    # See _pause_surplus above — ascending order, same reasoning.
    rows = (
        (
            await db.execute(
                select(StatusPage)
                .where(StatusPage.account_id == account_id, StatusPage.is_public.is_(True))
                .order_by(StatusPage.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    surplus = rows[max_count:] if max_count >= 0 else []
    for row in surplus:
        row.is_public = False
        if row.access_token_hash is None:
            row.access_token_hash = hash_token(new_raw_token())
    return [row.id for row in surplus]


async def apply_plan_limits(
    db: AsyncSession, account_id: uuid.UUID, plan: PlanLimits
) -> DowngradeReport:
    """Flushes but does not commit — the caller decides the transaction
    boundary. No caller exists in v1; tests call this directly."""
    paused_monitor_ids = await _pause_surplus(db, Monitor, account_id, plan.max_monitors)
    paused_heartbeat_ids = await _pause_surplus(db, Heartbeat, account_id, plan.max_heartbeats)
    raised_interval_monitor_ids = await _raise_floor(
        db, Monitor, account_id, "interval_seconds", plan.min_interval_seconds
    )
    # Heartbeats reuse min_interval_seconds — PLANS has no separate heartbeat
    # period minimum (Day 4 deviation; Day 10 may want to split this).
    raised_period_heartbeat_ids = await _raise_floor(
        db, Heartbeat, account_id, "period_seconds", plan.min_interval_seconds
    )
    unpublished_status_page_ids = await _unpublish_surplus(db, account_id, plan.max_status_pages)

    await db.flush()
    return DowngradeReport(
        paused_monitor_ids=paused_monitor_ids,
        paused_heartbeat_ids=paused_heartbeat_ids,
        raised_interval_monitor_ids=raised_interval_monitor_ids,
        raised_period_heartbeat_ids=raised_period_heartbeat_ids,
        unpublished_status_page_ids=unpublished_status_page_ids,
    )
