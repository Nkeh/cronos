"""Redis is explicitly non-critical: rate limits and caches only.

Nothing on the check or alert path may depend on Redis succeeding, so every
operation here reports failure instead of raising.
"""

from __future__ import annotations

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = structlog.get_logger()


class FailOpenRedis:
    def __init__(self, url: str) -> None:
        self._client: Redis = Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )

    async def ping(self) -> bool:
        try:
            return bool(await self._client.ping())
        except RedisError as exc:
            logger.warning("redis_unavailable", error=str(exc))
            return False
        except OSError as exc:
            # DNS/connection failures surface as OSError, not RedisError.
            logger.warning("redis_unavailable", error=str(exc))
            return False

    async def close(self) -> None:
        await self._client.aclose()
