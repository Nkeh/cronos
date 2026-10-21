"""Webhook signing (SRS Section 10 / CLAUDE.md): v1=HMAC-SHA256(secret, f"{timestamp}.{body}").

Pure, dependency-free functions -- independently testable against a fixed vector, and
independently reimplemented (not imported) by chaos/app/main.py, since that's a separate
deployable proving the scheme really is verifiable from the wire bytes alone.
"""

from __future__ import annotations

import hashlib
import hmac


def sign(secret: bytes, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret, f"{timestamp}.".encode("ascii") + body, hashlib.sha256)
    return f"v1={mac.hexdigest()}"


def verify(secret: bytes, timestamp: int, body: bytes, signature_header: str) -> bool:
    expected = sign(secret, timestamp, body)
    return hmac.compare_digest(expected, signature_header)
