"""Integration tests against the LIVE chaos container (reachable as host "chaos" on the Compose
default network -- these only pass when run inside a container on that network, e.g. via
`docker compose exec api pytest -q`, never from a bare host). Drives real HttpProbe.check()
calls against each chaos mode to prove the guard, timings, and error classification end to end,
not just against fakes."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

import httpx
import pytest_asyncio

from app.engine.claim import ClaimedMonitor
from app.engine.http_probe import HttpProbe

_ALLOW_HOSTS = frozenset({"chaos"})


def _monitor(path: str, **overrides) -> ClaimedMonitor:
    defaults = dict(
        id=uuid.uuid4(),
        url=f"http://chaos:8000{path}",
        method="GET",
        expected_status="2xx",
        timeout_seconds=5,
        scheduled_for=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return ClaimedMonitor(**defaults)


def _probe(**overrides) -> HttpProbe:
    kwargs = dict(user_agent="Cronos/1.0 (+http://localhost/bot)", allow_hosts=_ALLOW_HOSTS)
    kwargs.update(overrides)
    return HttpProbe(**kwargs)


@pytest_asyncio.fixture
async def chaos_control():
    async with httpx.AsyncClient(base_url="http://chaos:8000", trust_env=False, timeout=5) as client:

        async def _set(path: str, **fields) -> None:
            body = {"path": path, "mode": fields.pop("mode"), **fields}
            resp = await client.post("/_control", json=body)
            resp.raise_for_status()

        yield _set


async def test_up_mode_reports_is_up_with_full_timings(chaos_control) -> None:
    path = f"/{uuid.uuid4().hex}"
    await chaos_control(path, mode="up")

    result = await _probe().check(_monitor(path))

    assert result.is_up is True
    assert result.error_kind is None
    assert result.status_code == 200
    assert result.timings is not None
    for key in ("dns_ms", "connect_ms", "ttfb_ms", "total_ms"):
        assert key in result.timings


async def test_down_mode_reports_http_status(chaos_control) -> None:
    path = f"/{uuid.uuid4().hex}"
    await chaos_control(path, mode="down", status_code=503)

    result = await _probe().check(_monitor(path))

    assert result.is_up is False
    assert result.error_kind == "http_status"
    assert result.status_code == 503


async def test_slow_mode_within_timeout_succeeds(chaos_control) -> None:
    path = f"/{uuid.uuid4().hex}"
    await chaos_control(path, mode="slow", delay_ms=200)

    result = await _probe().check(_monitor(path, timeout_seconds=5))

    assert result.is_up is True
    assert result.response_time_ms >= 200


async def test_hang_mode_times_out(chaos_control) -> None:
    path = f"/{uuid.uuid4().hex}"
    await chaos_control(path, mode="hang")

    start = time.monotonic()
    result = await _probe().check(_monitor(path, timeout_seconds=2))
    elapsed = time.monotonic() - start

    assert result.is_up is False
    assert result.error_kind == "timeout"
    assert 1.5 <= elapsed <= 5


async def test_flap_mode_alternates_across_consecutive_checks(chaos_control) -> None:
    path = f"/{uuid.uuid4().hex}"
    await chaos_control(path, mode="flap", status_code=503, flap_every=1)

    results = [await _probe().check(_monitor(path)) for _ in range(4)]

    assert [r.is_up for r in results] == [True, False, True, False]


async def test_redirect_to_metadata_address_is_blocked(chaos_control) -> None:
    path = f"/{uuid.uuid4().hex}"
    await chaos_control(
        path, mode="redirect", redirect_url="http://169.254.169.254/", redirect_status=302
    )

    result = await _probe().check(_monitor(path))

    assert result.is_up is False
    assert result.error_kind == "blocked"


async def test_redirect_loop_exceeds_max_redirects(chaos_control) -> None:
    path_a = f"/{uuid.uuid4().hex}"
    path_b = f"/{uuid.uuid4().hex}"
    await chaos_control(path_a, mode="redirect", redirect_url=f"http://chaos:8000{path_b}")
    await chaos_control(path_b, mode="redirect", redirect_url=f"http://chaos:8000{path_a}")

    result = await _probe(max_redirects=3).check(_monitor(path_a))

    assert result.is_up is False
    assert result.error_kind == "redirects"


async def test_big_mode_body_capped_completes_quickly(chaos_control) -> None:
    path = f"/{uuid.uuid4().hex}"
    await chaos_control(path, mode="big", big_bytes=10 * 1024 * 1024)

    start = time.monotonic()
    result = await _probe(body_cap_bytes=65536).check(_monitor(path, timeout_seconds=10))
    elapsed = time.monotonic() - start

    assert result.is_up is True
    assert elapsed < 5, "the 64 KB cap should stop reading long before 10 MB finishes streaming"


async def test_tls_bad_mode_reports_tls_error_kind() -> None:
    monitor = ClaimedMonitor(
        id=uuid.uuid4(),
        url="https://chaos:8443/",
        method="GET",
        expected_status="2xx",
        timeout_seconds=5,
        scheduled_for=datetime.now(timezone.utc),
    )

    result = await _probe().check(monitor)

    assert result.is_up is False
    assert result.error_kind == "tls"
