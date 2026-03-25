"""Async Redis client factory with connection pooling and health check.

Provides factory functions for creating and closing async Redis clients,
and a simple health check class for verifying Redis connectivity.
"""

from __future__ import annotations

import redis.asyncio as aioredis


def create_redis_client(redis_url: str) -> aioredis.Redis:
    """Create an async Redis client from a URL.

    Uses redis.asyncio.Redis.from_url which internally creates a
    ConnectionPool for efficient connection reuse.

    Args:
        redis_url: Redis connection URL (e.g. redis://localhost:6379/0).

    Returns:
        Configured async Redis client instance.
    """
    return aioredis.Redis.from_url(
        redis_url,
        decode_responses=True,
    )


async def close_redis_client(client: aioredis.Redis) -> None:
    """Close an async Redis client and release its connection pool.

    Args:
        client: The Redis client to close.
    """
    await client.aclose()


class RedisHealthCheck:
    """Simple health check for Redis connectivity.

    Runs a PING command and reports whether Redis responded correctly.
    """

    def __init__(self, client: aioredis.Redis) -> None:
        self._client = client

    async def is_healthy(self) -> bool:
        """Check if Redis is responding.

        Returns:
            True if Redis responds to PING, False on any error.
        """
        try:
            result = await self._client.ping()
            # ping() returns True (bool) or "PONG" (str) depending on decode_responses
            return result is True or result == "PONG"
        except Exception:
            return False
