"""Settings, plus the production guard that CLAUDE.md requires.

The guard refuses to start the process at all when ENV=production and any of
the three unsafe conditions holds, with a clear message naming each reason.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from argon2 import PasswordHasher as _DefaultPasswordHasher
from pydantic_settings import BaseSettings, SettingsConfigDict

EXAMPLE_SECRET_KEY = "change-me-dev-only-not-for-production"

# Reading argon2-cffi's own constructor defaults means "production uses
# library defaults" is literally true with zero production-side config.
_ARGON2_DEFAULTS = _DefaultPasswordHasher()


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
    redis_url_test: str | None = None

    email_host: str = "mailpit"
    email_port: int = 1025
    email_from: str = "alerts@cronos.local"
    email_use_tls: bool = False

    # Three well-known, deliberately lightweight connectivity-check endpoints, one per major
    # infra provider, so a single provider's regional blip doesn't read as "Cronos is broken":
    #   - Google's own captive-portal check (204, near-zero payload, built for frequent polling)
    #   - Cloudflare's edge trace page (200, plain text, served from every PoP)
    #   - Apple's captive-portal check (200, plain HTML, also built for frequent polling)
    # Dev .env overrides this to point at chaos paths instead (see compose.override.yaml).
    canary_urls: str = (
        "https://www.google.com/generate_204,"
        "https://www.cloudflare.com/cdn-cgi/trace,"
        "http://captive.apple.com/hotspot-detect.html"
    )
    watchdog_url: str | None = None
    sentry_dsn: str | None = None

    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None

    ssrf_allow_hosts: str | None = None
    watch_polling: bool = True

    # ---- Auth (Day 3) ----
    cookie_secure: bool = True

    # Dev/test override these to cheap values via .env; production never sets
    # them, so these fall back to argon2-cffi's own real defaults.
    argon2_time_cost: int = _ARGON2_DEFAULTS.time_cost
    argon2_memory_cost: int = _ARGON2_DEFAULTS.memory_cost
    argon2_parallelism: int = _ARGON2_DEFAULTS.parallelism
    argon2_hash_len: int = _ARGON2_DEFAULTS.hash_len
    argon2_salt_len: int = _ARGON2_DEFAULTS.salt_len

    session_absolute_ttl_days: int = 30
    session_idle_ttl_days: int = 7
    session_last_seen_bump_seconds: int = 300
    verify_token_ttl_hours: int = 24
    reset_token_ttl_hours: int = 1

    rate_limit_login_ip_max: int = 10
    rate_limit_login_ip_window_seconds: int = 60
    rate_limit_login_email_ip_failures_max: int = 5
    rate_limit_login_email_ip_failures_window_seconds: int = 900
    rate_limit_login_email_failures_max: int = 30
    rate_limit_login_email_failures_window_seconds: int = 3600
    rate_limit_signup_ip_max: int = 5
    rate_limit_signup_ip_window_seconds: int = 3600
    rate_limit_reset_request_email_max: int = 3
    rate_limit_reset_request_email_window_seconds: int = 3600
    rate_limit_reset_request_ip_max: int = 10
    rate_limit_reset_request_ip_window_seconds: int = 3600
    rate_limit_verify_resend_user_max: int = 3
    rate_limit_verify_resend_user_window_seconds: int = 3600

    # ---- API keys (Day 4) ----
    # Abuse protection, not a plan-size limit, so it lives here rather than in
    # PLANS. Enforced inside authenticate() itself (see app/auth/api_keys.py),
    # not per-router, so it covers every route an API key can reach.
    rate_limit_api_key_max: int = 600
    rate_limit_api_key_window_seconds: int = 60

    # Comma-separated IPs of proxies we trust to set X-Forwarded-For (i.e. Caddy).
    trusted_proxy_ips: str = "127.0.0.1"

    # ---- Runner (Day 6) ----
    runner_concurrency: int = 50
    runner_drain_seconds: int = 8
    runner_task_margin_seconds: int = 10
    runner_claim_lock_timeout_ms: int = 2000
    runner_claim_statement_timeout_ms: int = 5000
    # NOT sized to runner_concurrency -- a task holds a connection only for its brief result
    # write, never while the probe itself is in flight (see _run_one), so concurrent tasks don't
    # need one connection apiece. Sized instead for how many of those short writes land at once;
    # a pool-checkout timeout is just a lost slot (see runner.py's PoolTimeoutError handling).
    runner_pool_size: int = 10
    runner_max_overflow: int = 5
    runner_pool_timeout_seconds: int = 5

    stub_probe_delay_min_ms: int = 50
    stub_probe_delay_max_ms: int = 300
    stub_probe_outcome: Literal["up", "down"] = "up"

    # The production guard below still refuses to start with PROBE_KIND=stub explicitly set --
    # deliberate: a stub probe that always reports "up" must never run where it could be
    # mistaken for real monitoring. The default is now "http" so production is safe with zero
    # config.
    probe_kind: Literal["stub", "http"] = "http"

    # ---- Probe (Day 7) ----
    probe_max_redirects: int = 3  # SRS Section 13: monitors get <=3 hops; webhooks (Day 9) get 0.
    probe_body_cap_bytes: int = 65536  # Read at most this much of a response body, then discard.
    probe_host_cap_per_minute: int = 60  # Politeness cap: checks/min to one target host, all accounts.

    # ---- Incidents / canaries (Day 8) ----
    recheck_delay_seconds: int = 30  # First failure -> re-check this soon, before confirming.
    canary_interval_seconds: int = 30  # Per SRS Section 7.

    @property
    def canary_urls_list(self) -> tuple[str, ...]:
        return tuple(u.strip() for u in self.canary_urls.split(",") if u.strip())

    @property
    def trusted_proxy_ips_set(self) -> frozenset[str]:
        return frozenset(
            ip.strip() for ip in self.trusted_proxy_ips.split(",") if ip.strip()
        )

    @property
    def ssrf_allow_hosts_set(self) -> frozenset[str]:
        if not self.ssrf_allow_hosts:
            return frozenset()
        return frozenset(
            host.strip().lower() for host in self.ssrf_allow_hosts.split(",") if host.strip()
        )

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
        if not self.cookie_secure:
            reasons.append(
                "COOKIE_SECURE is false; session/CSRF cookies would be sent over plain HTTP"
            )
        if self.probe_kind == "stub":
            reasons.append(
                "PROBE_KIND is stub; a probe that always reports \"up\" must never run in "
                "production"
            )
        if len(self.canary_urls_list) < 3:
            reasons.append(
                f"CANARY_URLS has only {len(self.canary_urls_list)} endpoint(s); production "
                "needs at least 3 so a single provider's blip can't look like Cronos's own "
                "failure"
            )

        if reasons:
            bullets = "\n".join(f"  - {reason}" for reason in reasons)
            raise ConfigurationError(f"Refusing to start in production:\n{bullets}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
