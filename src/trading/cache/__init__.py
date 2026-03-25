"""Cache layer for the trading system.

Exports:
    create_redis_client: Factory for async Redis clients.
    close_redis_client: Cleanly close a Redis client.
    RedisHealthCheck: Simple PING-based Redis health checker.
"""

from trading.cache.redis import RedisHealthCheck, close_redis_client, create_redis_client

__all__ = [
    "RedisHealthCheck",
    "close_redis_client",
    "create_redis_client",
]
