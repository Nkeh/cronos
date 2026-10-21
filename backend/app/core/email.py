"""Async transactional email for auth (verify/already-registered/reset).

The EmailSender Protocol (same shape as core/clock.py's Clock) is what lets a
provider-API backend slot in later without touching call sites: swap
SMTPEmailSender for e.g. a Postmark/Resend sender, nothing else changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Literal, Protocol

import aiosmtplib
import structlog

from app.core.config import Settings
from app.notifications.cause_copy import cause_copy

logger = structlog.get_logger()


@dataclass
class EmailMessage:
    to: str
    subject: str
    text_body: str
    html_body: str


class EmailSender(Protocol):
    async def send(self, message: EmailMessage) -> None: ...


class SMTPEmailSender:
    """Talks to Mailpit in dev, any real SMTP server in prod."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, message: EmailMessage) -> None:
        mime = MIMEMultipart("alternative")
        mime["Subject"] = message.subject
        mime["From"] = self._settings.email_from
        mime["To"] = message.to
        mime.attach(MIMEText(message.text_body, "plain"))
        mime.attach(MIMEText(message.html_body, "html"))

        await aiosmtplib.send(
            mime,
            hostname=self._settings.email_host,
            port=self._settings.email_port,
            use_tls=self._settings.email_use_tls,
        )


class FakeEmailSender:
    """Test double — captures sent messages instead of delivering them."""

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.sent.append(message)


def render_verify_email(to: str, link: str) -> EmailMessage:
    text_body = (
        "Cronos.\n\n"
        "Confirm your email address to finish setting up your account:\n\n"
        f"{link}\n\n"
        "This link expires in 24 hours."
    )
    html_body = (
        "<p><strong>Cronos.</strong></p>"
        "<p>Confirm your email address to finish setting up your account:</p>"
        f'<p><a href="{link}">{link}</a></p>'
        "<p>This link expires in 24 hours.</p>"
    )
    return EmailMessage(to=to, subject="Verify your Cronos account", text_body=text_body, html_body=html_body)


def render_already_registered_email(to: str) -> EmailMessage:
    text_body = (
        "Cronos.\n\n"
        "Someone just tried to sign up for Cronos using this email address, "
        "which already has an account.\n\n"
        "If this was you, log in as usual. If it wasn't, no action is needed — "
        "your account is unaffected."
    )
    html_body = (
        "<p><strong>Cronos.</strong></p>"
        "<p>Someone just tried to sign up for Cronos using this email address, "
        "which already has an account.</p>"
        "<p>If this was you, log in as usual. If it wasn't, no action is needed — "
        "your account is unaffected.</p>"
    )
    return EmailMessage(
        to=to, subject="Someone tried to register with your email", text_body=text_body, html_body=html_body
    )


def render_reset_email(to: str, link: str) -> EmailMessage:
    text_body = (
        "Cronos.\n\n"
        "Reset your password using this link:\n\n"
        f"{link}\n\n"
        "This link expires in 1 hour. If you didn't request this, you can ignore this email."
    )
    html_body = (
        "<p><strong>Cronos.</strong></p>"
        "<p>Reset your password using this link:</p>"
        f'<p><a href="{link}">{link}</a></p>'
        "<p>This link expires in 1 hour. If you didn't request this, you can ignore this email.</p>"
    )
    return EmailMessage(to=to, subject="Reset your Cronos password", text_body=text_body, html_body=html_body)


def _format_duration(total_seconds: float) -> str:
    """"45s", "3m 20s", "2h 5m" -- mirrors frontend/src/features/incidents/duration.ts's
    formatDuration exactly, so an alert email's subject and the UI never disagree."""
    seconds = max(0, int(total_seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _format_utc(dt) -> str:  # datetime, kept untyped to avoid importing datetime just for a hint
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def render_incident_opened_email(
    *, to: str, monitor_name: str, cause: str, started_at, incident_link: str, channels_link: str
) -> EmailMessage:
    plain_cause = cause_copy(cause)
    subject = f"[Cronos] DOWN: {monitor_name} — {plain_cause}"
    text_body = (
        "Cronos.\n\n"
        f"{monitor_name} is down.\n\n"
        f"Reason: {plain_cause}\n"
        f"Since: {_format_utc(started_at)}\n\n"
        f"Incident: {incident_link}\n"
        f"Manage alert channels: {channels_link}"
    )
    html_body = (
        "<p><strong>Cronos.</strong></p>"
        f"<p><strong>{monitor_name}</strong> is down.</p>"
        f"<p>Reason: {plain_cause}<br>Since: {_format_utc(started_at)}</p>"
        f'<p><a href="{incident_link}">View incident</a></p>'
        f'<p><a href="{channels_link}">Manage alert channels</a></p>'
    )
    return EmailMessage(to=to, subject=subject, text_body=text_body, html_body=html_body)


def render_incident_resolved_email(
    *, to: str, monitor_name: str, duration_seconds: float, resolved_at, incident_link: str,
    channels_link: str,
) -> EmailMessage:
    duration = _format_duration(duration_seconds)
    subject = f"[Cronos] RECOVERED: {monitor_name} (down {duration})"
    text_body = (
        "Cronos.\n\n"
        f"{monitor_name} has recovered.\n\n"
        f"Down for: {duration}\n"
        f"Recovered: {_format_utc(resolved_at)}\n\n"
        f"Incident: {incident_link}\n"
        f"Manage alert channels: {channels_link}"
    )
    html_body = (
        "<p><strong>Cronos.</strong></p>"
        f"<p><strong>{monitor_name}</strong> has recovered.</p>"
        f"<p>Down for: {duration}<br>Recovered: {_format_utc(resolved_at)}</p>"
        f'<p><a href="{incident_link}">View incident</a></p>'
        f'<p><a href="{channels_link}">Manage alert channels</a></p>'
    )
    return EmailMessage(to=to, subject=subject, text_body=text_body, html_body=html_body)


def render_fail_ping_email(
    *, to: str, heartbeat_name: str, cause: str, incident_link: str, channels_link: str
) -> EmailMessage:
    """Day 10 reuses this unchanged for heartbeat fail-ping alerts -- written now because the
    outbox's `fail_ping` event (and this template) don't depend on anything heartbeat-specific
    beyond a name and a cause, both of which the heartbeat engine will supply the same way
    monitors do."""
    plain_cause = cause_copy(cause)
    subject = f"[Cronos] MISSED: {heartbeat_name} — {plain_cause}"
    text_body = (
        "Cronos.\n\n"
        f"{heartbeat_name} missed its check-in.\n\n"
        f"Reason: {plain_cause}\n\n"
        f"Incident: {incident_link}\n"
        f"Manage alert channels: {channels_link}"
    )
    html_body = (
        "<p><strong>Cronos.</strong></p>"
        f"<p><strong>{heartbeat_name}</strong> missed its check-in.</p>"
        f"<p>Reason: {plain_cause}</p>"
        f'<p><a href="{incident_link}">View incident</a></p>'
        f'<p><a href="{channels_link}">Manage alert channels</a></p>'
    )
    return EmailMessage(to=to, subject=subject, text_body=text_body, html_body=html_body)


def render_flapping_email(
    *, to: str, subject_name: str, phase: Literal["started", "ended"], channels_link: str
) -> EmailMessage:
    if phase == "started":
        subject = f"[Cronos] FLAPPING: {subject_name}"
        body_line = (
            f"{subject_name} is flapping (repeatedly failing and recovering). To avoid spamming "
            "you, further open/resolved alerts for it are paused until it's been stable for a "
            "while."
        )
    else:
        subject = f"[Cronos] STABLE: {subject_name}"
        body_line = f"{subject_name} has been stable. Normal alerting has resumed for it."
    text_body = f"Cronos.\n\n{body_line}\n\nManage alert channels: {channels_link}"
    html_body = (
        "<p><strong>Cronos.</strong></p>"
        f"<p>{body_line}</p>"
        f'<p><a href="{channels_link}">Manage alert channels</a></p>'
    )
    return EmailMessage(to=to, subject=subject, text_body=text_body, html_body=html_body)


def render_channel_test_email(*, to: str) -> EmailMessage:
    """The Channels API's "send test" button -- not an alert, no outbox row, no channels_link
    (the user is already on the page that sent this)."""
    text_body = "Cronos.\n\nThis is a test alert from your Cronos notification channel settings."
    html_body = (
        "<p><strong>Cronos.</strong></p>"
        "<p>This is a test alert from your Cronos notification channel settings.</p>"
    )
    return EmailMessage(to=to, subject="[Cronos] Test alert", text_body=text_body, html_body=html_body)


def render_cap_reached_email(*, to: str, kind: Literal["email", "webhook"], channels_link: str) -> EmailMessage:
    subject = "[Cronos] Daily alert limit reached"
    body_line = (
        f"Your account has reached today's daily limit for {kind} alerts. Further {kind} alerts "
        "will resume tomorrow (UTC). This is a launch-period limit for cost and abuse "
        "protection, not a reflection of how many incidents you actually had."
    )
    text_body = f"Cronos.\n\n{body_line}\n\nManage alert channels: {channels_link}"
    html_body = (
        "<p><strong>Cronos.</strong></p>"
        f"<p>{body_line}</p>"
        f'<p><a href="{channels_link}">Manage alert channels</a></p>'
    )
    return EmailMessage(to=to, subject=subject, text_body=text_body, html_body=html_body)
