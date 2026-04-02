"""Redis pub/sub distribution and latest-value caching for market data.

Publishes quote and Greeks snapshots to Redis pub/sub channels for real-time
consumers, and maintains HSET latest-value caches for on-demand lookups.
All Redis operations are non-fatal: errors are logged but never raised,
following the Phase 1 decision that cache failures should not halt trading.

Channel naming convention:
  - Quotes:    mktdata:quote:{symbol}
  - Greeks:    mktdata:greeks:{symbol}:{con_id}
  - Staleness: mktdata:stale
  - Quote cache:  mktdata:latest:quote:{symbol}
  - Greeks cache: mktdata:latest:greeks:{con_id}
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import structlog
from redis.asyncio import Redis

from trading.market_data.models import GreeksSnapshot, QuoteSnapshot


class RedisDistributor:
    """Distributes market data via Redis pub/sub and HSET caching.

    Each quote/greeks update is both published to a pub/sub channel
    (for streaming consumers) and stored in an HSET (for latest-value
    lookups). This dual-write pattern allows both push and pull access.

    All Redis operations are wrapped in try/except. On failure, a warning
    is logged but no exception is raised (non-fatal cache errors).

    Args:
        redis_client: Async Redis client instance (decode_responses=True).
    """

    QUOTE_CHANNEL = "mktdata:quote:{symbol}"
    GREEKS_CHANNEL = "mktdata:greeks:{symbol}:{con_id}"
    STALENESS_CHANNEL = "mktdata:stale"
    QUOTE_HASH = "mktdata:latest:quote:{symbol}"
    GREEKS_HASH = "mktdata:latest:greeks:{con_id}"

    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client
        self._log = structlog.get_logger().bind(
            component="redis_distributor",
        )

    async def publish_quote(self, snapshot: QuoteSnapshot) -> None:
        """Publish a quote snapshot to Redis pub/sub and HSET cache.

        The snapshot is serialized to JSON and published to the symbol's
        quote channel. A mapping of all fields is stored in an HSET for
        latest-value retrieval.

        Args:
            snapshot: Quote snapshot to publish.
        """
        try:
            channel = self.QUOTE_CHANNEL.format(symbol=snapshot.symbol)
            payload = snapshot.model_dump_json()
            await self._redis.publish(channel, payload)

            hash_key = self.QUOTE_HASH.format(symbol=snapshot.symbol)
            mapping = {
                k: json.dumps(v) if not isinstance(v, str) else v
                for k, v in snapshot.model_dump(mode="json").items()
            }
            await self._redis.hset(hash_key, mapping=mapping)
        except Exception as e:
            self._log.warning(
                "redis.publish_quote_failed",
                symbol=snapshot.symbol,
                error=str(e),
            )

    async def publish_greeks(self, snapshot: GreeksSnapshot) -> None:
        """Publish a Greeks snapshot to Redis pub/sub and HSET cache.

        Same dual-write pattern as publish_quote, using the Greeks-specific
        channel and hash key naming.

        Args:
            snapshot: Greeks snapshot to publish.
        """
        try:
            channel = self.GREEKS_CHANNEL.format(
                symbol=snapshot.symbol,
                con_id=snapshot.con_id,
            )
            payload = snapshot.model_dump_json()
            await self._redis.publish(channel, payload)

            hash_key = self.GREEKS_HASH.format(con_id=snapshot.con_id)
            mapping = {
                k: json.dumps(v) if not isinstance(v, str) else v
                for k, v in snapshot.model_dump(mode="json").items()
            }
            await self._redis.hset(hash_key, mapping=mapping)
        except Exception as e:
            self._log.warning(
                "redis.publish_greeks_failed",
                symbol=snapshot.symbol,
                con_id=snapshot.con_id,
                error=str(e),
            )

    async def publish_stale(
        self,
        con_id: int,
        symbol: str,
        seconds_since_update: float,
    ) -> None:
        """Publish a staleness alert to the staleness channel.

        Notifies subscribers that a market data subscription has not
        received updates beyond the configured threshold.

        Args:
            con_id: Contract ID of the stale subscription.
            symbol: Symbol of the stale subscription.
            seconds_since_update: Seconds since last data update.
        """
        try:
            payload = json.dumps({
                "con_id": con_id,
                "symbol": symbol,
                "seconds_since_update": seconds_since_update,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            await self._redis.publish(self.STALENESS_CHANNEL, payload)
        except Exception as e:
            self._log.warning(
                "redis.publish_stale_failed",
                con_id=con_id,
                symbol=symbol,
                error=str(e),
            )

    async def get_latest_quote(self, symbol: str) -> dict | None:
        """Retrieve the latest cached quote for a symbol.

        Args:
            symbol: Ticker symbol to look up.

        Returns:
            Dict of quote fields if cached, None if not found or on error.
        """
        try:
            hash_key = self.QUOTE_HASH.format(symbol=symbol)
            data = await self._redis.hgetall(hash_key)
            return data if data else None
        except Exception as e:
            self._log.warning(
                "redis.get_latest_quote_failed",
                symbol=symbol,
                error=str(e),
            )
            return None

    async def get_latest_greeks(self, con_id: int) -> dict | None:
        """Retrieve the latest cached Greeks for an option contract.

        Args:
            con_id: Contract ID to look up.

        Returns:
            Dict of Greeks fields if cached, None if not found or on error.
        """
        try:
            hash_key = self.GREEKS_HASH.format(con_id=con_id)
            data = await self._redis.hgetall(hash_key)
            return data if data else None
        except Exception as e:
            self._log.warning(
                "redis.get_latest_greeks_failed",
                con_id=con_id,
                error=str(e),
            )
            return None
