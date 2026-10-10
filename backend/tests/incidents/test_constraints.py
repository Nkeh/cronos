from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.incidents.models import HEARTBEAT_CAUSES, MONITOR_CAUSES, Incident
from app.monitors.models import Monitor
from tests.helpers import make_account, make_heartbeat, make_incident, make_monitor


async def test_exactly_one_subject_rejects_both_null(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    with pytest.raises(IntegrityError):
        await make_incident(db_session, account.id, monitor_id=None, heartbeat_id=None)
    await db_session.rollback()


async def test_exactly_one_subject_rejects_both_set(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    monitor = await make_monitor(db_session, account.id)
    heartbeat = await make_heartbeat(db_session, account.id)
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await make_incident(
            db_session, account.id, monitor_id=monitor.id, heartbeat_id=heartbeat.id
        )
    await db_session.rollback()


async def test_cause_check_rejects_unknown_value(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    monitor = await make_monitor(db_session, account.id)
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await make_incident(db_session, account.id, monitor_id=monitor.id, cause="made_up")
    await db_session.rollback()


async def test_cause_must_match_subject_type(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    heartbeat = await make_heartbeat(db_session, account.id)
    await db_session.commit()

    # a heartbeat-shaped incident with a monitor-only cause must fail
    with pytest.raises(IntegrityError):
        await make_incident(
            db_session,
            account.id,
            heartbeat_id=heartbeat.id,
            cause="http_status",
        )
    await db_session.rollback()


@pytest.mark.parametrize("cause", MONITOR_CAUSES)
async def test_every_monitor_cause_is_accepted(db_session: AsyncSession, cause: str) -> None:
    account = await make_account(db_session)
    monitor = await make_monitor(db_session, account.id)
    await db_session.commit()
    incident = await make_incident(db_session, account.id, monitor_id=monitor.id, cause=cause)
    assert incident.cause == cause


@pytest.mark.parametrize("cause", HEARTBEAT_CAUSES)
async def test_every_heartbeat_cause_is_accepted(db_session: AsyncSession, cause: str) -> None:
    account = await make_account(db_session)
    heartbeat = await make_heartbeat(db_session, account.id)
    await db_session.commit()
    incident = await make_incident(db_session, account.id, heartbeat_id=heartbeat.id, cause=cause)
    assert incident.cause == cause


async def test_confirmed_at_must_not_precede_started_at(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    monitor = await make_monitor(db_session, account.id)
    await db_session.commit()

    now = datetime.now(timezone.utc)
    with pytest.raises(IntegrityError):
        await make_incident(
            db_session,
            account.id,
            monitor_id=monitor.id,
            started_at=now,
            confirmed_at=now - timedelta(seconds=5),
        )
    await db_session.rollback()


async def test_resolved_at_must_not_precede_started_at(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    monitor = await make_monitor(db_session, account.id)
    await db_session.commit()

    now = datetime.now(timezone.utc)
    with pytest.raises(IntegrityError):
        await make_incident(
            db_session,
            account.id,
            monitor_id=monitor.id,
            started_at=now,
            resolved_at=now - timedelta(seconds=5),
        )
    await db_session.rollback()


async def test_one_open_incident_per_monitor(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    monitor = await make_monitor(db_session, account.id)
    first = await make_incident(db_session, account.id, monitor_id=monitor.id)
    account_id, monitor_id, first_id = account.id, monitor.id, first.id
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await make_incident(db_session, account_id, monitor_id=monitor_id)
    await db_session.rollback()  # expires account/monitor/first — use the captured ids below

    # resolving the first incident makes a new one possible
    await db_session.execute(
        update(Incident)
        .where(Incident.id == first_id)
        .values(resolved_at=datetime.now(timezone.utc))
    )
    await db_session.commit()

    await make_incident(db_session, account_id, monitor_id=monitor_id)
    await db_session.commit()


async def test_one_open_incident_per_heartbeat(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    heartbeat = await make_heartbeat(db_session, account.id)
    await make_incident(db_session, account.id, heartbeat_id=heartbeat.id)
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await make_incident(db_session, account.id, heartbeat_id=heartbeat.id)
    await db_session.rollback()


async def test_incident_account_id_must_match_monitor_owner(db_session: AsyncSession) -> None:
    owner_account = await make_account(db_session)
    other_account = await make_account(db_session)
    monitor = await make_monitor(db_session, owner_account.id)
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await make_incident(db_session, other_account.id, monitor_id=monitor.id)
    await db_session.rollback()


async def test_deleting_monitor_cascades_incident(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    monitor = await make_monitor(db_session, account.id)
    incident = await make_incident(db_session, account.id, monitor_id=monitor.id)
    monitor_id, incident_id = monitor.id, incident.id
    await db_session.commit()

    await db_session.delete(await db_session.get(Monitor, monitor_id))
    await db_session.commit()
    db_session.expire_all()

    assert await db_session.get(Incident, incident_id) is None


async def test_valid_incident_succeeds(db_session: AsyncSession) -> None:
    account = await make_account(db_session)
    monitor = await make_monitor(db_session, account.id)
    await db_session.commit()
    incident = await make_incident(db_session, account.id, monitor_id=monitor.id)
    assert incident.resolved_at is None
