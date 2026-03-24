"""Shared dependency providers for FastAPI routes.

Provides async Redis client factory for SSE pub/sub connections.
Uses REDIS_URL env var with REDIS_PROGRESS_DB for database number.
"""

import os

from redis.asyncio import Redis as AsyncRedis

_async_redis: AsyncRedis | None = None


async def get_async_redis() -> AsyncRedis:
    """Get async Redis client for SSE pub/sub.

    Uses REDIS_URL env var with REDIS_PROGRESS_DB for database number.
    Creates a singleton connection reused across requests.
    """
    global _async_redis
    if _async_redis is None:
        base_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        db = int(os.environ.get("REDIS_PROGRESS_DB", "2"))
        base = base_url.rsplit("/", 1)[0]
        _async_redis = AsyncRedis.from_url(f"{base}/{db}")
    return _async_redis


async def close_async_redis() -> None:
    """Close async Redis connection. Call on app shutdown."""
    global _async_redis
    if _async_redis is not None:
        await _async_redis.aclose()
        _async_redis = None
