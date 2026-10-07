"""Settings, plus the production guard that CLAUDE.md requires.

The guard refuses to start the process at all when ENV=production and any of
the three unsafe conditions holds, with a clear message naming each reason.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

EXAMPLE_SECRET_KEY = "change-me-dev-only-not-for-production"


class ConfigurationError(RuntimeError):
    """Raised when the current settings are unsafe to run with."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["development", "test", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    public_origin: str = "http://localhost:8080"

    secret_key: str = EXAMPLE_SECRET_KEY
    encryption_key: str = EXAMPLE_SECRET_KEY

    database_url: str
    database_url_test: str | None = None

    redis_url: str = "redis://redis:6379/0"

    email_host: str = "mailpit"
    email_port: int = 1025
    email_from: str = "alerts@cronos.local"
    email_use_tls: bool = False

    canary_urls: str = ""
    watchdog_url: str | None = None
    sentry_dsn: str | None = None

    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None

    ssrf_allow_hosts: str | None = None
    watch_polling: bool = True

    def check_production_guard(self) -> None:
        if self.env != "production":
            return

        reasons: list[str] = []
        if self.ssrf_allow_hosts:
            reasons.append(
                "SSRF_ALLOW_HOSTS is set; the dev-only SSRF allowlist must never run in production"
            )
        if not self.secret_key or self.secret_key == EXAMPLE_SECRET_KEY:
            reasons.append("SECRET_KEY is missing or still the example placeholder value")
        if self.debug:
            reasons.append("DEBUG is enabled")

        if reasons:
            bullets = "\n".join(f"  - {reason}" for reason in reasons)
            raise ConfigurationError(f"Refusing to start in production:\n{bullets}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
