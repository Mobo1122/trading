"""Market data manager orchestrating IB events to Redis and TimescaleDB.

This is the top-level coordinator for the real-time market data pipeline.
It hooks into IB's pendingTickersEvent to receive batch tick updates, then:
  1. Updates subscription last_seen timestamps (for staleness detection)
  2. Creates QuoteSnapshot and publishes via RedisDistributor (pub/sub + HSET)
  3. Buffers snapshots in TimescaleDBWriter (batch flush every 5s)
  4. For options, also extracts and distributes GreeksSnapshot

This module delegates subscription lifecycle to SubscriptionManager and
provides a high-level API for the rest of the system.
"""

from __future__ import annotations

import asyncio

import structlog
from ib_async import IB, Option, Ticker

from trading.config import Settings
from trading.market_data.distributor import RedisDistributor
from trading.market_data.models import (
    GreeksSnapshot,
    QuoteSnapshot,
    SubscriptionPriority,
)
from trading.market_data.subscriber import SubscriptionManager
from trading.market_data.writer import TimescaleDBWriter


class MarketDataManager:
    """Orchestrates the full IB -> Redis + TimescaleDB market data pipeline.

    Connects IB's tick event system to the distribution and persistence
    layers. Manages subscriptions via SubscriptionManager and provides
    a unified API for subscribing to market data.

    Args:
        ib: Connected IB async client instance.
        subscriber: SubscriptionManager for line tracking and eviction.
        distributor: RedisDistributor for pub/sub and caching.
        writer: TimescaleDBWriter for batch persistence.
        settings: Application settings.
    """

    def __init__(
        self,
        ib: IB,
        subscriber: SubscriptionManager,
        distributor: RedisDistributor,
        writer: TimescaleDBWriter,
        settings: Settings,
    ) -> None:
        self._ib = ib
        self._subscriber = subscriber
        self._distributor = distributor
        self._writer = writer
        self._settings = settings

        self._ib.pendingTickersEvent += self._on_pending_tickers

        self._log = structlog.get_logger().bind(
            component="market_data_manager",
        )
        self._log.info("market_data.manager_initialized")

    async def subscribe_watchlist(self) -> None:
        """Subscribe to market data for all watchlist symbols.

        Iterates through settings.market_data.watchlist and subscribes
        each symbol as an underlying with MEDIUM priority.
        """
        count = 0
        for symbol in self._settings.market_data.watchlist:
            result = await self._subscriber.subscribe_underlying(
                symbol,
                priority=SubscriptionPriority.MEDIUM,
            )
            if result is not None:
                count += 1

        self._log.info(
            "market_data.watchlist_subscribed",
            total=len(self._settings.market_data.watchlist),
            newly_subscribed=count,
        )

    async def subscribe_underlying(
        self,
        symbol: str,
        priority: SubscriptionPriority = SubscriptionPriority.MEDIUM,
    ) -> Ticker | None:
        """Subscribe to market data for an underlying symbol.

        Delegates to SubscriptionManager.

        Args:
            symbol: Ticker symbol (e.g. "AAPL").
            priority: Subscription priority for eviction ordering.

        Returns:
            IB Ticker if newly subscribed, None otherwise.
        """
        return await self._subscriber.subscribe_underlying(symbol, priority)

    async def subscribe_option(
        self,
        contract: Option,
        priority: SubscriptionPriority = SubscriptionPriority.LOW,
    ) -> Ticker | None:
        """Subscribe to market data for an option contract.

        Delegates to SubscriptionManager (which auto-subscribes the
        underlying if needed).

        Args:
            contract: IB Option contract.
            priority: Subscription priority for eviction ordering.

        Returns:
            IB Ticker if newly subscribed, None otherwise.
        """
        return await self._subscriber.subscribe_option(contract, priority)

    async def unsubscribe(self, con_id: int) -> bool:
        """Cancel a market data subscription.

        Args:
            con_id: Contract ID to unsubscribe.

        Returns:
            True if subscription was found and cancelled.
        """
        return await self._subscriber.unsubscribe(con_id)

    def _on_pending_tickers(self, tickers: set) -> None:
        """Handle batch tick updates from IB.

        Called by ib_async's event loop when any subscribed ticker has
        new data. Processes each ticker: updates staleness tracking,
        publishes to Redis, and buffers for database persistence.

        For option contracts with available modelGreeks, also extracts
        and distributes Greeks snapshots.

        Args:
            tickers: Set of IB Ticker objects with pending updates.
        """
        for ticker in tickers:
            if ticker.contract is None:
                continue

            # Update staleness tracking
            self._subscriber.update_last_seen(ticker.contract.conId)

            # Create and distribute quote snapshot (all contract types)
            snapshot = QuoteSnapshot.from_ticker(ticker)
            asyncio.create_task(self._distributor.publish_quote(snapshot))
            self._writer.buffer_quote(snapshot)

            # For options with available Greeks, also distribute Greeks
            if (
                ticker.contract.secType == "OPT"
                and ticker.modelGreeks is not None
            ):
                greeks_snapshot = GreeksSnapshot.from_ticker(ticker)
                if greeks_snapshot is not None:
                    asyncio.create_task(
                        self._distributor.publish_greeks(greeks_snapshot)
                    )
                    self._writer.buffer_greeks(greeks_snapshot)

    async def start(self) -> None:
        """Start the market data pipeline.

        Starts the TimescaleDB writer's flush loop and subscribes
        to all watchlist symbols.
        """
        await self._writer.start()
        await self.subscribe_watchlist()
        self._log.info("market_data.started")

    async def stop(self) -> None:
        """Stop the market data pipeline.

        Unhooks the tick event handler and stops the writer (which
        performs a final flush of buffered data).
        """
        self._ib.pendingTickersEvent -= self._on_pending_tickers
        await self._writer.stop()
        self._log.info("market_data.stopped")
