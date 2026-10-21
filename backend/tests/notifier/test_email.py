"""Unit tests for deliver_email's outcome classification. Patches aiosmtplib.send (the one call
SMTPEmailSender.send makes) so the mapping is exercised against the real except-chain in
app/notifier/email.py, not reimplemented here -- same approach as
tests/engine/test_error_classification.py for HttpProbe.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import aiosmtplib
import pytest

from app.core.config import get_settings
from app.notifier.delivery import DeliveryContext
from app.notifier.email import deliver_email

# In production these are always real DeliveryContext fields reused across other events too, so
# the dataclass itself keeps them Optional -- but every Incident.started_at is NOT NULL, and
# delivery.py never builds a context for "opened"/"resolved" from a None value, so a realistic
# default here is a real datetime, not None.
_INCIDENT_STARTED_AT = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
_INCIDENT_RESOLVED_AT = datetime(2026, 10, 20, 12, 1, 0, tzinfo=timezone.utc)


def _ctx(event: str = "opened", **overrides) -> DeliveryContext:
    defaults = dict(
        notification_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        event=event,
        payload={},
        attempts=1,
        channel_id=uuid.uuid4(),
        channel_kind="email",
        channel_config={"address": "ops@example.com"},
        channel_secret=None,
        subject_name="api",
        incident_id=uuid.uuid4(),
        incident_cause="http_status",
        incident_started_at=_INCIDENT_STARTED_AT,
        incident_resolved_at=_INCIDENT_RESOLVED_AT,
        incident_duration_seconds=1.0,
        flap_phase="started",
        cap_kind="email",
    )
    defaults.update(overrides)
    return DeliveryContext(**defaults)


async def _deliver_with_send_raising(exc: Exception | None, *, event: str = "opened"):
    with patch("aiosmtplib.send", new=AsyncMock(side_effect=exc)):
        return await deliver_email(get_settings(), _ctx(event=event))


async def test_successful_send_is_sent() -> None:
    outcome = await _deliver_with_send_raising(None)
    assert outcome.outcome == "sent"


async def test_smtp_4xx_response_is_a_retry() -> None:
    exc = aiosmtplib.SMTPResponseException(450, "mailbox busy")
    outcome = await _deliver_with_send_raising(exc)
    assert outcome.outcome == "retry"
    assert outcome.status_code == 450


async def test_smtp_5xx_response_is_a_permanent_failure() -> None:
    exc = aiosmtplib.SMTPResponseException(550, "mailbox unavailable")
    outcome = await _deliver_with_send_raising(exc)
    assert outcome.outcome == "failed"
    assert outcome.status_code == 550


async def test_connect_error_is_a_retry() -> None:
    exc = aiosmtplib.SMTPConnectError("connection refused")
    outcome = await _deliver_with_send_raising(exc)
    assert outcome.outcome == "retry"


async def test_unexpected_error_is_a_failure_not_a_crash() -> None:
    outcome = await _deliver_with_send_raising(RuntimeError("boom"))
    assert outcome.outcome == "failed"


@pytest.mark.parametrize(
    "event", ["opened", "resolved", "fail_ping", "flapping", "cap_reached"]
)
async def test_every_event_renders_without_raising(event: str) -> None:
    outcome = await _deliver_with_send_raising(None, event=event)
    assert outcome.outcome == "sent"
