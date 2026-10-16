"""Per-target-host politeness cap (SRS Section 13): at most N checks per minute to one host,
across all accounts. A host hitting its cap is evidence of Cronos's own aggregate load, not
evidence the target is down, so runner.py skips the check entirely for this cycle rather than
writing a dishonest result.

Reuses FailOpenRedis.incr_with_ttl directly rather than app.auth.rate_limit's
enforce_rate_limit, which is ApiError/HTTP-coupled -- this is an engine-internal throttle, not
an HTTP response. FailOpenRedis already logs redis_unavailable/redis_recovered once per outage
episode, so no duplicate logging is needed here: a Redis outage must never block probing.
"""

from __future__ import annotations

from app.core.redis import FailOpenRedis


def _host_cap_key(host: str) -> str:
    return f"ratelimit:probe:host:{host}"


async def check_host_cap(redis: FailOpenRedis, host: str, *, limit_per_minute: int) -> bool:
    """True = within budget, or Redis is down (fail open). False = the caller should skip this
    check entirely this cycle."""
    result = await redis.incr_with_ttl(_host_cap_key(host), window_seconds=60)
    if result is None:
        return True
    count, _ttl = result
    return count <= limit_per_minute
