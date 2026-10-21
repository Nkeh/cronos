"""Webhook-secret encryption at rest (CLAUDE.md / SRS Section 13).

ENCRYPTION_KEY is a plain arbitrary-length string setting (same shape as SECRET_KEY) -- Fernet
requires an exact 32-byte urlsafe-base64 key, so one is deterministically derived here via
SHA-256 rather than asking operators to generate and store a second, differently-shaped secret.

Known limitation, not addressed today: rotating ENCRYPTION_KEY makes every already-stored secret
undecryptable. No rotation mechanism exists yet; out of scope for Day 9.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

__all__ = ["encrypt_secret", "decrypt_secret", "InvalidToken"]


def _fernet_key(encryption_key: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(encryption_key.encode("utf-8")).digest())


def encrypt_secret(raw: bytes, encryption_key: str) -> bytes:
    return Fernet(_fernet_key(encryption_key)).encrypt(raw)


def decrypt_secret(token: bytes, encryption_key: str) -> bytes:
    return Fernet(_fernet_key(encryption_key)).decrypt(token)
