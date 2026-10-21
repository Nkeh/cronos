"""Plan-limit checks.

check_limit and check_interval_minimum are plain functions, NEVER wrapped as
a FastAPI Depends(). A FastAPI dependency resolves before the route body
runs and its effects (here, a row lock) stay open for the rest of the
request — including anything the route body awaits afterward, e.g.
ssrf_policy's DNS lookup, an arbitrary-latency network call that must never
happen while check_limit's account row lock is held. So every route that
calls check_limit runs ALL validation first (schema parsing, the full
ssrf_policy sequence including the DNS check), then enters one short final
block with no intervening await on anything but the DB: lock the account row
via get_account_for_update, call check_limit, construct/insert the new row,
commit.

get_account_for_update is the ONLY place in the codebase that takes a row
lock (grep for with_for_update to confirm) — every caller must route through
it rather than calling db.get(..., with_for_update=True) directly, because a
bare db.get() with a primary key already present in the session's identity
map returns the cached object WITHOUT re-querying, silently skipping the
lock. populate_existing=True is what forces a real query (and therefore a
real FOR UPDATE) every time, regardless of what else this session already
loaded this request.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import Account
from app.auth.models import ApiKey
from app.core.errors import ApiError
from app.heartbeats.models import Heartbeat
from app.monitors.models import Monitor
from app.notifications.models import NotificationChannel
from app.plans.config import PlanLimits, get_plan

_RESOURCE_MODELS: dict[str, type] = {
    "monitors": Monitor,
    "heartbeats": Heartbeat,
    "api_keys": ApiKey,
    "channels": NotificationChannel,
}


async def check_limit(db: AsyncSession, account: Account, resource: str) -> None:
    """Counts `resource` rows for `account` (the caller must already hold
    account's row lock) and raises 422 plan_limit if at/over the plan max.
    api_keys counts only non-revoked rows — revoking a key frees a slot."""
    plan = get_plan(account.plan)
    model = _RESOURCE_MODELS[resource]
    limit = getattr(plan, f"max_{resource}")

    stmt = select(func.count()).select_from(model).where(model.account_id == account.id)
    if resource == "api_keys":
        stmt = stmt.where(model.revoked_at.is_(None))

    count = (await db.execute(stmt)).scalar_one()
    if count >= limit:
        raise ApiError(422, "plan_limit", f"The {plan.name} plan allows up to {limit} {resource}.")


def check_interval_minimum(interval_seconds: int, plan: PlanLimits) -> None:
    if interval_seconds < plan.min_interval_seconds:
        raise ApiError(
            422,
            "plan_limit",
            f"The {plan.name} plan's minimum interval is {plan.min_interval_seconds}s.",
            field="interval_seconds",
        )


async def get_account_for_update(db: AsyncSession, account_id: uuid.UUID) -> Account:
    """Always emits a real SELECT ... FOR UPDATE, even if `account_id` was
    already loaded into this session's identity map earlier in the request —
    populate_existing=True forces a genuine re-query instead of returning a
    cached object (which with_for_update=True alone would silently do,
    skipping the lock). See the module docstring."""
    account = await db.get(
        Account, account_id, with_for_update=True, populate_existing=True
    )
    assert account is not None
    return account
