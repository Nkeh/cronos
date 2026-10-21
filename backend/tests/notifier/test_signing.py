from __future__ import annotations

import hashlib
import hmac

from app.notifier.signing import sign, verify


def test_known_vector_matches_an_independent_implementation() -> None:
    """The expected value here is computed with a fresh stdlib hmac call, not by calling sign()
    to produce its own expected value -- an independently-verified test vector."""
    secret = b"test-secret"
    timestamp = 1700000000
    body = b'{"id":"abc","event":"opened"}'

    expected_hex = hmac.new(secret, f"{timestamp}.".encode("ascii") + body, hashlib.sha256).hexdigest()

    assert sign(secret, timestamp, body) == f"v1={expected_hex}"


def test_verify_accepts_a_matching_signature() -> None:
    secret = b"another-secret"
    timestamp = 1700000001
    body = b"{}"
    header = sign(secret, timestamp, body)
    assert verify(secret, timestamp, body, header) is True


def test_verify_rejects_a_tampered_body() -> None:
    secret = b"another-secret"
    timestamp = 1700000001
    header = sign(secret, timestamp, b"{}")
    assert verify(secret, timestamp, b'{"tampered":true}', header) is False


def test_verify_rejects_wrong_secret() -> None:
    timestamp = 1700000001
    body = b"{}"
    header = sign(b"secret-a", timestamp, body)
    assert verify(b"secret-b", timestamp, body, header) is False
