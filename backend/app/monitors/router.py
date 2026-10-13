"""Monitor CRUD: /api/v1/monitors.

check_limit/check_interval_minimum are never Depends() here — see
app/plans/dependencies.py's module docstring. Every write runs ALL
validation first (schema parsing already happened via FastAPI; the full
ssrf_policy sequence, DNS included, runs explicitly in the route body), then
enters one short final block: lock the account row, call check_limit,
mutate/insert, commit — no await on anything but the DB inside that block.
"""

from __future__ import annotations

import random
import uuid

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import Account
from app.auth.dependencies import AuthContext, require_scope, require_verified
from app.auth.models import User
from app.core.config import Settings
from app.core.db import get_db_session
from app.core.dependencies import get_settings_dep
from app.core.errors import ApiError
from app.engine import ssrf_policy
from app.monitors.models import Monitor
from app.monitors.schemas import MonitorCreate, MonitorPatch, MonitorPublic
from app.plans.config import get_plan
from app.plans.dependencies import check_interval_minimum, check_limit, get_account_for_update

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/monitors", tags=["monitors"])

_TARGET_FIELDS = frozenset({"url", "method", "expected_status"})


def _validate_url(raw_url: str, settings: Settings) -> ssrf_policy.ParsedUrl:
    try:
        return ssrf_policy.normalize_and_validate_url(
            raw_url, allow_hosts=settings.ssrf_allow_hosts_set
        )
    except ssrf_policy.UrlPolicyError as exc:
        raise ApiError(422, exc.code, exc.message, field="url") from None


async def _validate_url_resolves(parsed: ssrf_policy.ParsedUrl, settings: Settings) -> None:
    try:
        await ssrf_policy.check_dns_resolves_public(
            parsed.host, allow_hosts=settings.ssrf_allow_hosts_set
        )
    except ssrf_policy.UrlPolicyError as exc:
        raise ApiError(422, exc.code, exc.message, field="url") from None


async def _get_owned_monitor(
    db: AsyncSession, account_id: uuid.UUID, monitor_id: uuid.UUID
) -> Monitor:
    monitor = (
        await db.execute(
            select(Monitor).where(Monitor.account_id == account_id, Monitor.id == monitor_id)
        )
    ).scalar_one_or_none()
    if monitor is None:
        raise ApiError(404, "not_found", "Monitor not found.")
    return monitor


async def _rejitter(db: AsyncSession, monitor_id: uuid.UUID, interval_seconds: int) -> None:
    jitter_seconds = round(random.uniform(0, interval_seconds), 3)
    await db.execute(
        update(Monitor)
        .where(Monitor.id == monitor_id)
        .values(
            next_check_at=text("now() + make_interval(secs => :jitter)").bindparams(
                jitter=jitter_seconds
            )
        )
    )


@router.get("", response_model=list[MonitorPublic])
async def list_monitors(
    principal: AuthContext = Depends(require_scope("monitors:read")),
    db: AsyncSession = Depends(get_db_session),
) -> list[MonitorPublic]:
    rows = (
        (
            await db.execute(
                select(Monitor)
                .where(Monitor.account_id == principal.user.account_id)
                .order_by(Monitor.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [MonitorPublic.model_validate(row) for row in rows]


@router.get("/{monitor_id}", response_model=MonitorPublic)
async def get_monitor(
    monitor_id: uuid.UUID,
    principal: AuthContext = Depends(require_scope("monitors:read")),
    db: AsyncSession = Depends(get_db_session),
) -> MonitorPublic:
    monitor = await _get_owned_monitor(db, principal.user.account_id, monitor_id)
    return MonitorPublic.model_validate(monitor)


@router.post("", response_model=MonitorPublic, status_code=201)
async def create_monitor(
    payload: MonitorCreate,
    user: User = Depends(require_verified),
    _scope: AuthContext = Depends(require_scope("monitors:write")),
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings_dep),
) -> MonitorPublic:
    # --- validation phase: no lock held yet ---
    parsed = _validate_url(payload.url, settings)
    await _validate_url_resolves(parsed, settings)

    # A scalar column query rather than db.get(Account, ...) — purely a
    # lighter-weight read (no ORM object constructed) now that
    # get_account_for_update is itself hardened (populate_existing=True)
    # against the identity-map trap this used to have to dodge by hand.
    account_plan = (
        await db.execute(select(Account.plan).where(Account.id == user.account_id))
    ).scalar_one()
    check_interval_minimum(payload.interval_seconds, get_plan(account_plan))

    # --- short final block: lock -> count -> insert -> commit, DB-only awaits ---
    account = await get_account_for_update(db, user.account_id)
    await check_limit(db, account, "monitors")

    monitor = Monitor(
        account_id=account.id,
        name=payload.name,
        url=parsed.normalized_url,
        method=payload.method,
        expected_status=payload.expected_status,
        interval_seconds=payload.interval_seconds,
        timeout_seconds=payload.timeout_seconds,
        confirm_threshold=payload.confirm_threshold,
    )
    db.add(monitor)
    await db.flush()
    await _rejitter(db, monitor.id, payload.interval_seconds)
    await db.commit()
    await db.refresh(monitor)

    logger.info("monitor_created", monitor_id=str(monitor.id), account_id=str(account.id))
    return MonitorPublic.model_validate(monitor)


@router.patch("/{monitor_id}", response_model=MonitorPublic)
async def patch_monitor(
    monitor_id: uuid.UUID,
    payload: MonitorPatch,
    user: User = Depends(require_verified),
    _scope: AuthContext = Depends(require_scope("monitors:write")),
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings_dep),
) -> MonitorPublic:
    monitor = await _get_owned_monitor(db, user.account_id, monitor_id)
    data = payload.model_dump(exclude_unset=True)

    if "url" in data:
        parsed = _validate_url(data["url"], settings)
        await _validate_url_resolves(parsed, settings)
        data["url"] = parsed.normalized_url

    if "interval_seconds" in data:
        account = await db.get(Account, user.account_id)
        assert account is not None
        check_interval_minimum(data["interval_seconds"], get_plan(account.plan))

    target_changed = bool(_TARGET_FIELDS & data.keys())
    if target_changed:
        # Consecutive-failure/ewma state resets unconditionally — there's
        # nothing CHECK-constrained about those columns, and stale
        # failure/anomaly state has no reason to survive a target change just
        # because the monitor happens to be paused. Only `status` follows the
        # pause rule, since the DB's paused_matches_active CHECK requires it.
        monitor.consecutive_failures = 0
        monitor.ewma_mean = None
        monitor.ewma_var = None
        monitor.ewma_n = 0
        monitor.status = "paused" if not monitor.is_active else "new"

    for field_name, value in data.items():
        setattr(monitor, field_name, value)

    if monitor.timeout_seconds >= monitor.interval_seconds:
        raise ApiError(
            422,
            "validation_error",
            "timeout_seconds must be less than interval_seconds.",
            field="timeout_seconds",
        )

    await db.flush()
    if "interval_seconds" in data:
        await _rejitter(db, monitor.id, monitor.interval_seconds)
    await db.commit()
    await db.refresh(monitor)

    logger.info("monitor_patched", monitor_id=str(monitor.id), fields=sorted(data))
    return MonitorPublic.model_validate(monitor)


@router.delete("/{monitor_id}", status_code=204)
async def delete_monitor(
    monitor_id: uuid.UUID,
    user: User = Depends(require_verified),
    _scope: AuthContext = Depends(require_scope("monitors:write")),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    monitor = await _get_owned_monitor(db, user.account_id, monitor_id)
    await db.delete(monitor)
    await db.commit()
    logger.info("monitor_deleted", monitor_id=str(monitor_id), account_id=str(user.account_id))


@router.post("/{monitor_id}/check-now", status_code=204)
async def check_now(
    monitor_id: uuid.UUID,
    user: User = Depends(require_verified),
    _scope: AuthContext = Depends(require_scope("monitors:write")),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    monitor = await _get_owned_monitor(db, user.account_id, monitor_id)
    if not monitor.is_active:
        raise ApiError(409, "monitor_paused", "Cannot check a paused monitor.")
    await db.execute(
        update(Monitor).where(Monitor.id == monitor.id).values(next_check_at=text("now()"))
    )
    await db.commit()


@router.post("/{monitor_id}/pause", response_model=MonitorPublic)
async def pause_monitor(
    monitor_id: uuid.UUID,
    user: User = Depends(require_verified),
    _scope: AuthContext = Depends(require_scope("monitors:write")),
    db: AsyncSession = Depends(get_db_session),
) -> MonitorPublic:
    # TODO (Day 8): decide what pausing does to an open incident.
    monitor = await _get_owned_monitor(db, user.account_id, monitor_id)
    monitor.is_active = False
    monitor.status = "paused"
    await db.commit()
    await db.refresh(monitor)
    return MonitorPublic.model_validate(monitor)


@router.post("/{monitor_id}/resume", response_model=MonitorPublic)
async def resume_monitor(
    monitor_id: uuid.UUID,
    user: User = Depends(require_verified),
    _scope: AuthContext = Depends(require_scope("monitors:write")),
    db: AsyncSession = Depends(get_db_session),
) -> MonitorPublic:
    monitor = await _get_owned_monitor(db, user.account_id, monitor_id)
    monitor.is_active = True
    monitor.status = "new"
    monitor.consecutive_failures = 0
    await db.flush()
    await _rejitter(db, monitor.id, monitor.interval_seconds)
    await db.commit()
    await db.refresh(monitor)
    return MonitorPublic.model_validate(monitor)
