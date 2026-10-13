"""Redis is explicitly non-critical: rate limits and caches only.

Nothing on the check or alert path may depend on Redis succeeding, so every
operation here reports failure instead of raising.
"""

from __future__ import annotations

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = structlog.get_logger()

# INCR + conditional EXPIRE + TTL-read, as one atomic unit. A plain INCR then
# a separate EXPIRE call would leave a window (e.g. a process dying between
# the two) where a counter key exists with no expiry at all, i.e. a rate-limit
# key that never clears. Redis runs a whole script as one atomic step, so
# that window can't happen.
_INCR_WITH_TTL_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return {count, redis.call('TTL', KEYS[1])}
"""


class FailOpenRedis:
    def __init__(self, url: str) -> None:
        self._client: Redis = Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        self._incr_with_ttl_script = self._client.register_script(_INCR_WITH_TTL_SCRIPT)
        self._breaker_tripped = False

    def _on_failure(self, exc: Exception) -> None:
        # Log once per outage episode, not once per failed call.
        if not self._breaker_tripped:
            logger.warning("redis_unavailable", error=str(exc))
            self._breaker_tripped = True

    def _on_success(self) -> None:
        if self._breaker_tripped:
            logger.info("redis_recovered")
        self._breaker_tripped = False

    async def ping(self) -> bool:
        try:
            result = bool(await self._client.ping())
            self._on_success()
            return result
        except (RedisError, OSError) as exc:
            # DNS/connection failures surface as OSError, not RedisError.
            self._on_failure(exc)
            return False

    async def incr_with_ttl(self, key: str, window_seconds: int) -> tuple[int, int] | None:
        """Atomically increments `key`, setting its TTL on first use.

        Returns (count, ttl_seconds_remaining), or None if Redis is down
        (callers must fail open — allow the request — on None).
        """
        try:
            count, ttl = await self._incr_with_ttl_script(
                keys=[key], args=[window_seconds]
            )
            self._on_success()
            return int(count), int(ttl)
        except (RedisError, OSError) as exc:
            self._on_failure(exc)
            return None

    async def get_count(self, key: str) -> int | None:
        """Reads a counter without incrementing it. 0 if absent, None if Redis is down."""
        try:
            value = await self._client.get(key)
            self._on_success()
            return int(value) if value is not None else 0
        except (RedisError, OSError) as exc:
            self._on_failure(exc)
            return None

    async def get_ttl(self, key: str) -> int | None:
        try:
            ttl = await self._client.ttl(key)
            self._on_success()
            return int(ttl)
        except (RedisError, OSError) as exc:
            self._on_failure(exc)
            return None

    async def delete_key(self, key: str) -> None:
        try:
            await self._client.delete(key)
            self._on_success()
        except (RedisError, OSError) as exc:
            self._on_failure(exc)

    async def close(self) -> None:
        await self._client.aclose()
