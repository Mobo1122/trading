"""Redis-backed caching for option chains and qualified contracts.

Provides a cache layer that stores option chain data and qualified
contract details in Redis with configurable TTL. This avoids redundant
IB API calls for the same chain data, which is critical because
reqSecDefOptParams has rate limits.

Cache keys:
  - chain:{SYMBOL} -> JSON-serialized option chain dict
  - contract:{CON_ID} -> JSON-serialized contract dict
"""

from __future__ import annotations

import json

import structlog
from redis.asyncio import Redis

logger = structlog.get_logger()


class ContractCache:
    """Redis-backed cache for option chains and qualified contracts.

    Stores chain data as JSON strings with a configurable TTL (default 1 hour).
    All cache operations are fire-and-forget: failures log warnings but never
    raise, because caching is an optimization and must not break the
    critical path.

    Args:
        redis_client: An async Redis client (from redis.asyncio).
        ttl: Cache entry time-to-live in seconds. Default 3600 (1 hour).
    """

    CHAIN_PREFIX = "chain:"
    CONTRACT_PREFIX = "contract:"

    def __init__(self, redis_client: Redis, ttl: int = 3600) -> None:
        self.redis = redis_client
        self.ttl = ttl
        self._log = logger.bind(component="contract_cache")

    async def get_chain(self, symbol: str) -> dict | None:
        """Retrieve cached option chain data for a symbol.

        Args:
            symbol: The underlying symbol (e.g., "AAPL").

        Returns:
            Deserialized chain dict if found, None on cache miss or error.
        """
        try:
            raw = await self.redis.get(f"{self.CHAIN_PREFIX}{symbol}")
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as e:
            self._log.warning("cache.get_chain_failed", symbol=symbol, error=str(e))
            return None

    async def set_chain(self, symbol: str, chain_data: dict) -> None:
        """Store option chain data in the cache.

        Serializes the chain dict to JSON and stores with TTL. Lists and
        other iterables in chain_data are preserved as JSON arrays.

        Args:
            symbol: The underlying symbol.
            chain_data: Dict with keys: symbol, exchange, trading_class,
                multiplier, expirations (list of YYYYMMDD), strikes (list of floats).
        """
        try:
            raw = json.dumps(chain_data)
            await self.redis.set(
                f"{self.CHAIN_PREFIX}{symbol}",
                raw,
                ex=self.ttl,
            )
        except Exception as e:
            self._log.warning("cache.set_chain_failed", symbol=symbol, error=str(e))

    async def invalidate_chain(self, symbol: str) -> None:
        """Remove cached chain data for a symbol.

        Used when fresh data is needed (e.g., new trading day, new
        expirations added).

        Args:
            symbol: The underlying symbol to invalidate.
        """
        try:
            await self.redis.delete(f"{self.CHAIN_PREFIX}{symbol}")
        except Exception as e:
            self._log.warning(
                "cache.invalidate_chain_failed", symbol=symbol, error=str(e)
            )

    async def get_qualified_contract(self, con_id: int) -> dict | None:
        """Retrieve a cached qualified contract by contract ID.

        Args:
            con_id: The IB contract ID.

        Returns:
            Deserialized contract dict if found, None on miss or error.
        """
        try:
            raw = await self.redis.get(f"{self.CONTRACT_PREFIX}{con_id}")
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as e:
            self._log.warning(
                "cache.get_contract_failed", con_id=con_id, error=str(e)
            )
            return None

    async def set_qualified_contract(self, con_id: int, contract_data: dict) -> None:
        """Cache a qualified contract by its contract ID.

        Args:
            con_id: The IB contract ID.
            contract_data: Serializable dict of contract details.
        """
        try:
            raw = json.dumps(contract_data)
            await self.redis.set(
                f"{self.CONTRACT_PREFIX}{con_id}",
                raw,
                ex=self.ttl,
            )
        except Exception as e:
            self._log.warning(
                "cache.set_contract_failed", con_id=con_id, error=str(e)
            )
