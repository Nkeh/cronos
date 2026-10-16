from __future__ import annotations

import uuid

from app.core.config import get_settings
from app.core.redis import FailOpenRedis
from app.engine.host_cap import check_host_cap


def _redis() -> FailOpenRedis:
    return FailOpenRedis(get_settings().redis_url)


async def test_within_limit_returns_true() -> None:
    redis = _redis()
    host = f"host-{uuid.uuid4().hex}.example"
    try:
        for _ in range(5):
            assert await check_host_cap(redis, host, limit_per_minute=10) is True
    finally:
        await redis.close()


async def test_exceeding_limit_returns_false() -> None:
    redis = _redis()
    host = f"host-{uuid.uuid4().hex}.example"
    try:
        results = [await check_host_cap(redis, host, limit_per_minute=3) for _ in range(5)]
        assert results == [True, True, True, False, False]
    finally:
        await redis.close()


async def test_redis_down_fails_open() -> None:
    redis = FailOpenRedis("redis://127.0.0.1:1/0")
    host = f"host-{uuid.uuid4().hex}.example"
    try:
        for _ in range(10):
            assert await check_host_cap(redis, host, limit_per_minute=1) is True
    finally:
        await redis.close()
