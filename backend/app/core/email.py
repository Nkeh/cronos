"""Async transactional email for auth (verify/already-registered/reset).

The EmailSender Protocol (same shape as core/clock.py's Clock) is what lets a
provider-API backend slot in later without touching call sites: swap
SMTPEmailSender for e.g. a Postmark/Resend sender, nothing else changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Protocol

import aiosmtplib
import structlog

from app.core.config import Settings

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
