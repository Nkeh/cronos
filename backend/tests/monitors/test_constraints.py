from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.monitors.models import CheckResult, Monitor
from tests.helpers import make_account, make_check_result, make_monitor


@pytest.mark.parametrize(
    "overrides",
    [
        {"url": "ftp://example.com"},
        {"method": "POST"},
        {"expected_status": "banana"},
        {"interval_seconds": 10},
        {"timeout_seconds": 0},
        {"confirm_threshold": 0},
        {"status": "deleted"},
    ],
    ids=[
        "url_format",
        "method",
        "expected_status_format",
        "interval_floor",
        "timeout_range_low",
        "confirm_threshold_range",
        "status",
    ],
)
async def test_monitor_check_violations(
    db_session: AsyncSession, overrides: dict
) -> None:
    account = await make_account(db_session)
    with pytest.raises(IntegrityError):
        await make_monitor(db_session, account.id, **overrides)
    await db_session.rollback()


async def test_monitor_timeout_must_be_less_than_interval(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    with pytest.raises(IntegrityError):
        await make_monitor(
            db_session, account.id, interval_seconds=30, timeout_seconds=30
        )
    await db_session.rollback()


async def test_monitor_consecutive_failures_nonneg(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    with pytest.raises(IntegrityError):
        await make_monitor(db_session, account.id, consecutive_failures=-1)
    await db_session.rollback()


async def test_monitor_paused_matches_active_invariant_both_directions(
    db_session: AsyncSession,
) -> None:
    account = await make_account(db_session)
    account_id = account.id
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await make_monitor(db_session, account_id, status="paused", is_active=True)
    await db_session.rollback()  # expires `account` — account_id is captured, so safe to reuse

    with pytest.raises(IntegrityError):
        await make_monitor(db_session, account_id, status="new", is_active=False)
    await db_session.rollback()

    # valid counterpart in both directions
    await make_monitor(db_session, account_id, status="paused", is_active=False)
    await make_monitor(db_session, account_id, status="new", is_active=True)


async def test_monitor_valid_row_succeeds(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    monitor = await make_monitor(db_session, account.id)
    assert monitor.status == "new"
    assert monitor.is_active is True


async def test_check_result_status_code_range(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    monitor = await make_monitor(db_session, account.id)
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await make_check_result(db_session, monitor.id, status_code=999)
    await db_session.rollback()


async def test_check_result_response_time_nonneg(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    monitor = await make_monitor(db_session, account.id)
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await make_check_result(db_session, monitor.id, response_time_ms=-5)
    await db_session.rollback()


async def test_deleting_monitor_cascades_check_results(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    monitor = await make_monitor(db_session, account.id)
    result = await make_check_result(db_session, monitor.id)
    monitor_id, result_id = monitor.id, result.id
    await db_session.commit()

    await db_session.delete(await db_session.get(Monitor, monitor_id))
    await db_session.commit()
    db_session.expire_all()

    assert await db_session.get(CheckResult, result_id) is None
