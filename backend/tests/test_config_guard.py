from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import ConfigurationError, Settings


def _production_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "env": "production",
        "database_url": "postgresql+asyncpg://user:pw@db/cronos",
        "secret_key": "a-real-secret-key-value",
        "encryption_key": "a-real-encryption-key-value",
        "ssrf_allow_hosts": None,
        "debug": False,
        "cookie_secure": True,
    }
    base.update(overrides)
    return Settings(**base)


def test_refuses_when_ssrf_allow_hosts_is_set() -> None:
    settings = _production_settings(ssrf_allow_hosts="chaos")
    with pytest.raises(ConfigurationError, match="SSRF_ALLOW_HOSTS"):
        settings.check_production_guard()


def test_refuses_when_secret_key_is_the_example_value() -> None:
    settings = _production_settings(secret_key="change-me-dev-only-not-for-production")
    with pytest.raises(ConfigurationError, match="SECRET_KEY"):
        settings.check_production_guard()


def test_refuses_when_debug_is_enabled() -> None:
    settings = _production_settings(debug=True)
    with pytest.raises(ConfigurationError, match="DEBUG"):
        settings.check_production_guard()


def test_refuses_when_cookie_secure_is_false() -> None:
    settings = _production_settings(cookie_secure=False)
    with pytest.raises(ConfigurationError, match="COOKIE_SECURE"):
        settings.check_production_guard()


def test_allows_a_clean_production_configuration() -> None:
    settings = _production_settings()
    settings.check_production_guard()


def test_allows_ssrf_allow_hosts_outside_production() -> None:
    settings = _production_settings(env="development", ssrf_allow_hosts="chaos")
    settings.check_production_guard()


def test_rejects_unknown_env_value() -> None:
    with pytest.raises(ValidationError):
        _production_settings(env="prod")


def test_rejects_wrong_case_env_value() -> None:
    with pytest.raises(ValidationError):
        _production_settings(env="Production")
