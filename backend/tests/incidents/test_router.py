from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.incidents.router import _TIMELINE_LIMIT
from tests.helpers import (
    login_as,
    make_account,
    make_check_result,
    make_incident,
    make_monitor,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def test_cross_account_incident_get_is_404(
    client: AsyncClient, db_session: AsyncSession, app: FastAPI
) -> None:
    owner_account = await make_account(db_session)
    monitor = await make_monitor(db_session, owner_account.id)
    incident = await make_incident(db_session, owner_account.id, monitor_id=monitor.id)
    await db_session.commit()

    await login_as(client, db_session, app.state.clock)
    resp = await client.get(f"/api/v1/incidents/{incident.id}")
    assert resp.status_code == 404


async def test_cross_account_ack_is_404(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    owner_account = await make_account(db_session)
    monitor = await make_monitor(db_session, owner_account.id)
    incident = await make_incident(db_session, owner_account.id, monitor_id=monitor.id)
    await db_session.commit()

    await login_as(client, db_session, app.state.clock)
    resp = await client.post(
        f"/api/v1/incidents/{incident.id}/ack", json={}, headers=csrf_headers
    )
    assert resp.status_code == 404


async def test_list_pagination_full_then_partial_page(
    client: AsyncClient, db_session: AsyncSession, app: FastAPI
) -> None:
    user = await login_as(client, db_session, app.state.clock)
    monitor = await make_monitor(db_session, user.account_id)
    base = _utcnow() - timedelta(hours=1)
    incidents = []
    for i in range(7):
        incident = await make_incident(
            db_session,
            user.account_id,
            monitor_id=monitor.id,
            started_at=base + timedelta(minutes=i),
            resolved_at=base + timedelta(minutes=i, seconds=30),
            resolved_reason="recovered",
        )
        incidents.append(incident)
    await db_session.commit()

    page1 = await client.get("/api/v1/incidents", params={"limit": 5})
    assert page1.status_code == 200
    body1 = page1.json()
    assert len(body1["items"]) == 5
    assert body1["next_cursor"] is not None
    # newest (highest started_at) first
    returned_ids_1 = [item["id"] for item in body1["items"]]
    assert returned_ids_1 == [str(i.id) for i in reversed(incidents)][:5]

    page2 = await client.get(
        "/api/v1/incidents", params={"limit": 5, "cursor": body1["next_cursor"]}
    )
    assert page2.status_code == 200
    body2 = page2.json()
    assert len(body2["items"]) == 2
    assert body2["next_cursor"] is None
    returned_ids_2 = [item["id"] for item in body2["items"]]
    assert returned_ids_2 == [str(i.id) for i in reversed(incidents)][5:]


async def test_list_state_filter(
    client: AsyncClient, db_session: AsyncSession, app: FastAPI
) -> None:
    user = await login_as(client, db_session, app.state.clock)
    monitor = await make_monitor(db_session, user.account_id)
    open_incident = await make_incident(db_session, user.account_id, monitor_id=monitor.id)
    other_monitor = await make_monitor(db_session, user.account_id)
    resolve_base = _utcnow() - timedelta(minutes=5)
    resolved_incident = await make_incident(
        db_session,
        user.account_id,
        monitor_id=other_monitor.id,
        started_at=resolve_base,
        resolved_at=resolve_base + timedelta(minutes=1),
        resolved_reason="recovered",
    )
    await db_session.commit()

    open_resp = await client.get("/api/v1/incidents", params={"state": "open"})
    assert [item["id"] for item in open_resp.json()["items"]] == [str(open_incident.id)]

    resolved_resp = await client.get("/api/v1/incidents", params={"state": "resolved"})
    assert [item["id"] for item in resolved_resp.json()["items"]] == [str(resolved_incident.id)]


async def test_list_monitor_id_filter(
    client: AsyncClient, db_session: AsyncSession, app: FastAPI
) -> None:
    user = await login_as(client, db_session, app.state.clock)
    monitor_a = await make_monitor(db_session, user.account_id)
    monitor_b = await make_monitor(db_session, user.account_id)
    incident_a = await make_incident(db_session, user.account_id, monitor_id=monitor_a.id)
    await make_incident(db_session, user.account_id, monitor_id=monitor_b.id)
    await db_session.commit()

    resp = await client.get("/api/v1/incidents", params={"monitor_id": str(monitor_a.id)})
    assert [item["id"] for item in resp.json()["items"]] == [str(incident_a.id)]


async def test_ack_is_idempotent(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    user = await login_as(client, db_session, app.state.clock)
    monitor = await make_monitor(db_session, user.account_id)
    incident = await make_incident(db_session, user.account_id, monitor_id=monitor.id)
    await db_session.commit()

    first = await client.post(
        f"/api/v1/incidents/{incident.id}/ack", json={}, headers=csrf_headers
    )
    assert first.status_code == 200
    acknowledged_at_1 = first.json()["acknowledged_at"]
    assert acknowledged_at_1 is not None

    second = await client.post(
        f"/api/v1/incidents/{incident.id}/ack", json={}, headers=csrf_headers
    )
    assert second.status_code == 200
    assert second.json()["acknowledged_at"] == acknowledged_at_1


async def test_ack_on_resolved_incident_is_409(
    client: AsyncClient, csrf_headers: dict, db_session: AsyncSession, app: FastAPI
) -> None:
    user = await login_as(client, db_session, app.state.clock)
    monitor = await make_monitor(db_session, user.account_id)
    resolve_base = _utcnow() - timedelta(minutes=5)
    incident = await make_incident(
        db_session,
        user.account_id,
        monitor_id=monitor.id,
        started_at=resolve_base,
        resolved_at=resolve_base + timedelta(minutes=1),
        resolved_reason="recovered",
    )
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/incidents/{incident.id}/ack", json={}, headers=csrf_headers
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "incident_resolved"


async def test_open_count_matches_db(
    client: AsyncClient, db_session: AsyncSession, app: FastAPI
) -> None:
    user = await login_as(client, db_session, app.state.clock)
    monitor = await make_monitor(db_session, user.account_id)
    await make_incident(db_session, user.account_id, monitor_id=monitor.id)
    other_monitor = await make_monitor(db_session, user.account_id)
    resolve_base = _utcnow() - timedelta(minutes=5)
    await make_incident(
        db_session,
        user.account_id,
        monitor_id=other_monitor.id,
        started_at=resolve_base,
        resolved_at=resolve_base + timedelta(minutes=1),
        resolved_reason="recovered",
    )
    await db_session.commit()

    resp = await client.get("/api/v1/incidents/open-count")
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


async def test_timeline_bounded_and_newest_first(
    client: AsyncClient, db_session: AsyncSession, app: FastAPI
) -> None:
    user = await login_as(client, db_session, app.state.clock)
    monitor = await make_monitor(db_session, user.account_id)
    started_at = _utcnow() - timedelta(hours=1)
    incident = await make_incident(
        db_session, user.account_id, monitor_id=monitor.id, started_at=started_at
    )
    await db_session.commit()

    for i in range(_TIMELINE_LIMIT + 5):
        await make_check_result(
            db_session, monitor.id, checked_at=started_at + timedelta(seconds=i)
        )
    await db_session.commit()

    resp = await client.get(f"/api/v1/incidents/{incident.id}")
    assert resp.status_code == 200
    timeline = resp.json()["timeline"]
    assert len(timeline) == _TIMELINE_LIMIT
    # newest first
    checked_ats = [item["checked_at"] for item in timeline]
    assert checked_ats == sorted(checked_ats, reverse=True)
