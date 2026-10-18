"""The seam canary: drives a REAL HttpProbe end to end through the actual httpx.AsyncClient ->
AsyncHTTPTransport -> transport._pool swap (not GuardedBackend in isolation). This must fail
loudly if a future httpx/httpcore upgrade stops routing connections through our guarded pool --
see the wiring comment in http_probe.py pointing back at this test."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.engine.claim import ClaimedMonitor
from app.engine.http_probe import HttpProbe


async def test_blocked_address_through_real_transport() -> None:
    probe = HttpProbe(user_agent="Cronos/1.0 (+http://localhost/bot)")
    monitor = ClaimedMonitor(
        id=uuid.uuid4(),
        url="http://169.254.169.254/latest/meta-data",
        method="GET",
        expected_status="2xx",
        timeout_seconds=5,
        scheduled_for=datetime.now(timezone.utc),
        claimed_at=datetime.now(timezone.utc),
        claim_monotonic=0.0,
    )

    result = await probe.check(monitor)

    assert result.is_up is False
    assert result.error_kind == "blocked"
