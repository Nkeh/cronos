"""Email delivery. Constructs its own SMTPEmailSender (no FastAPI app.state -- same reasoning as
runner.py building its own HttpProbe) and calls .send() synchronously inside this module's own
try/except, so a delivery failure feeds the outcome classification below. Deliberately NOT
BackgroundTasks: CLAUDE.md's BackgroundTask exception is for auth emails only (verify/reset/
already-registered) -- alert emails always go through the outbox, retried and logged like any
other delivery.
"""

from __future__ import annotations

import aiosmtplib
import structlog

from app.core.config import Settings
from app.core.email import (
    EmailMessage,
    SMTPEmailSender,
    render_cap_reached_email,
    render_fail_ping_email,
    render_flapping_email,
    render_incident_opened_email,
    render_incident_resolved_email,
)
from app.notifier.delivery import DeliveryContext
from app.notifier.outcomes import DeliveryOutcome

logger = structlog.get_logger()

_MAX_ERROR_LENGTH = 500


def _render(settings: Settings, ctx: DeliveryContext) -> EmailMessage:
    channels_link = f"{settings.public_origin}/settings/channels"
    to = ctx.channel_config["address"]

    if ctx.event == "opened":
        incident_link = f"{settings.public_origin}/incidents/{ctx.incident_id}"
        return render_incident_opened_email(
            to=to, monitor_name=ctx.subject_name or "A monitor", cause=ctx.incident_cause,
            started_at=ctx.incident_started_at, incident_link=incident_link,
            channels_link=channels_link,
        )
    if ctx.event == "resolved":
        incident_link = f"{settings.public_origin}/incidents/{ctx.incident_id}"
        return render_incident_resolved_email(
            to=to, monitor_name=ctx.subject_name or "A monitor",
            duration_seconds=ctx.incident_duration_seconds or 0.0,
            resolved_at=ctx.incident_resolved_at, incident_link=incident_link,
            channels_link=channels_link,
        )
    if ctx.event == "fail_ping":
        incident_link = f"{settings.public_origin}/incidents/{ctx.incident_id}"
        return render_fail_ping_email(
            to=to, heartbeat_name=ctx.subject_name or "A heartbeat", cause=ctx.incident_cause,
            incident_link=incident_link, channels_link=channels_link,
        )
    if ctx.event == "flapping":
        return render_flapping_email(
            to=to, subject_name=ctx.subject_name or "A subject", phase=ctx.flap_phase or "started",
            channels_link=channels_link,
        )
    # cap_reached
    return render_cap_reached_email(to=to, kind=ctx.cap_kind or "email", channels_link=channels_link)


async def deliver_email(settings: Settings, ctx: DeliveryContext) -> DeliveryOutcome:
    """Duration is measured by the caller (app/notifier/__main__.py), around this whole call --
    nothing in here needs its own clock."""
    message = _render(settings, ctx)
    sender = SMTPEmailSender(settings)
    try:
        await sender.send(message)
    except aiosmtplib.SMTPResponseException as exc:
        if 400 <= exc.code < 500:
            return DeliveryOutcome(outcome="retry", status_code=exc.code, error=str(exc)[:_MAX_ERROR_LENGTH])
        return DeliveryOutcome(outcome="failed", status_code=exc.code, error=str(exc)[:_MAX_ERROR_LENGTH])
    except (aiosmtplib.SMTPConnectError, aiosmtplib.SMTPServerDisconnected, aiosmtplib.SMTPTimeoutError) as exc:
        return DeliveryOutcome(outcome="retry", error=str(exc)[:_MAX_ERROR_LENGTH])
    except Exception as exc:  # noqa: BLE001 - one bad delivery must never crash the notifier
        logger.warning("email_delivery_unclassified_error", error=str(exc)[:_MAX_ERROR_LENGTH])
        return DeliveryOutcome(outcome="failed", error=str(exc)[:_MAX_ERROR_LENGTH])

    return DeliveryOutcome(outcome="sent")
