from __future__ import annotations

import pytest

from app.core.crypto import InvalidToken, decrypt_secret, encrypt_secret


def test_round_trips_through_encrypt_and_decrypt() -> None:
    raw = b"super-secret-webhook-value"
    token = encrypt_secret(raw, "a-real-encryption-key")
    assert decrypt_secret(token, "a-real-encryption-key") == raw


def test_the_encrypted_value_is_never_the_raw_bytes() -> None:
    raw = b"super-secret-webhook-value"
    token = encrypt_secret(raw, "a-real-encryption-key")
    assert token != raw
    assert raw not in token


def test_decrypting_with_the_wrong_key_fails() -> None:
    token = encrypt_secret(b"value", "key-one")
    with pytest.raises(InvalidToken):
        decrypt_secret(token, "key-two")


def test_two_different_arbitrary_length_keys_derive_different_fernet_keys() -> None:
    token = encrypt_secret(b"value", "short")
    with pytest.raises(InvalidToken):
        decrypt_secret(token, "a-much-longer-key-string-than-short")
