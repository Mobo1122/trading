"""Subscription lifecycle management for IB market data lines.

Manages the 100-line IB subscription limit with priority-based LRU eviction.
Automatically subscribes underlyings when options are requested (required for
IB to populate Greeks). Tracks subscription metadata for staleness detection.

Key behaviors:
  - HIGH priority subscriptions are pinned and never evicted
  - When at capacity, the oldest non-pinned subscription is evicted (LRU)
  - Option subscriptions auto-trigger underlying subscription if missing
  - update_last_seen() is called on every tick for staleness tracking
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from ib_async import IB, Option, Stock, Ticker

from trading.config import Settings
from trading.market_data.models import SubscriptionInfo, SubscriptionPriority


class SubscriptionManager:
    """Manages IB market data subscriptions within the line limit.

    IB imposes a hard limit on concurrent market data lines (typically 100).
    This manager tracks all active subscriptions, enforces the limit via
    LRU eviction of low-priority subscriptions, and ensures underlyings
    are always subscribed before their options (Greeks dependency).

    Args:
        ib: Connected IB async client instance.
        settings: Application settings (reads market_data config).
    """

    def __init__(self, ib: IB, settings: Settings) -> None:
        self._ib = ib
        self._settings = settings
        self._max_lines: int = settings.market_data.max_subscription_lines
        self._reserved_lines: int = settings.market_data.reserved_lines

        self._active: dict[int, SubscriptionInfo] = {}
        self._contracts: dict[int, Stock | Option] = {}
        self._priority_pins: set[int] = set()
        self._underlying_map: dict[str, int] = {}

        self._log = structlog.get_logger().bind(
            component="subscription_manager",
        )

    @property
    def available_lines(self) -> int:
        """Number of subscription lines still available."""
        return self._max_lines - len(self._active)

    @property
    def active_count(self) -> int:
        """Number of currently active subscriptions."""
        return len(self._active)

    @property
    def active_subscriptions(self) -> dict[int, SubscriptionInfo]:
        """Copy of all active subscriptions (conId -> SubscriptionInfo)."""
        return dict(self._active)

    async def subscribe_underlying(
        self,
        symbol: str,
        priority: SubscriptionPriority = SubscriptionPriority.MEDIUM,
    ) -> Ticker | None:
        """Subscribe to market data for an underlying equity.

        If the symbol is already subscribed, returns None (caller can get
        the ticker from the IB object). If at capacity, attempts LRU eviction.

        Args:
            symbol: Ticker symbol (e.g. "AAPL", "SPY").
            priority: Subscription priority level for eviction ordering.

        Returns:
            IB Ticker object if newly subscribed, None if already active
            or if subscription failed (no evictable lines).
        """
        if symbol in self._underlying_map:
            self._log.debug(
                "subscription.underlying_already_active",
                symbol=symbol,
            )
            return None

        if self.available_lines <= 0:
            if not self._evict_one():
                self._log.warning(
                    "subscription.no_available_lines",
                    symbol=symbol,
                    active_count=self.active_count,
                )
                return None

        contract = Stock(symbol, "SMART", "USD")
        await self._ib.qualifyContractsAsync(contract)

        ticker = self._ib.reqMktData(
            contract,
            genericTickList="100,101,104,106,165",
        )

        now = datetime.now(timezone.utc)
        info = SubscriptionInfo(
            con_id=contract.conId,
            symbol=symbol,
            sec_type="STK",
            priority=priority,
            subscribed_at=now,
        )

        self._active[contract.conId] = info
        self._contracts[contract.conId] = contract
        self._underlying_map[symbol] = contract.conId

        if priority == SubscriptionPriority.HIGH:
            self._priority_pins.add(contract.conId)

        self._log.info(
            "subscription.underlying_added",
            symbol=symbol,
            con_id=contract.conId,
            active_count=self.active_count,
            available_lines=self.available_lines,
        )

        return ticker

    async def subscribe_option(
        self,
        contract: Option,
        priority: SubscriptionPriority = SubscriptionPriority.LOW,
    ) -> Ticker | None:
        """Subscribe to market data for an option contract.

        CRITICAL: If the underlying is not already subscribed, this method
        auto-subscribes it first with MEDIUM priority. IB will not populate
        Greeks for an option unless its underlying has an active data line.

        Args:
            contract: IB Option contract to subscribe.
            priority: Subscription priority level for eviction ordering.

        Returns:
            IB Ticker object if newly subscribed, None if already active
            or if subscription failed.
        """
        # Auto-subscribe underlying if not already active
        if contract.symbol not in self._underlying_map:
            self._log.info(
                "subscription.auto_subscribing_underlying",
                symbol=contract.symbol,
                reason="greeks_dependency",
            )
            result = await self.subscribe_underlying(
                contract.symbol,
                priority=SubscriptionPriority.MEDIUM,
            )
            if result is None and contract.symbol not in self._underlying_map:
                self._log.warning(
                    "subscription.underlying_auto_subscribe_failed",
                    symbol=contract.symbol,
                )
                return None

        # Check if option already subscribed
        if contract.conId != 0 and contract.conId in self._active:
            self._log.debug(
                "subscription.option_already_active",
                con_id=contract.conId,
            )
            return None

        if self.available_lines <= 0:
            if not self._evict_one():
                self._log.warning(
                    "subscription.no_available_lines_option",
                    symbol=contract.symbol,
                    active_count=self.active_count,
                )
                return None

        # Qualify if conId not yet resolved
        if contract.conId == 0:
            await self._ib.qualifyContractsAsync(contract)

        # Double-check after qualify in case conId was resolved and already active
        if contract.conId in self._active:
            return None

        ticker = self._ib.reqMktData(
            contract,
            genericTickList="100,101",
        )

        now = datetime.now(timezone.utc)
        info = SubscriptionInfo(
            con_id=contract.conId,
            symbol=contract.symbol,
            sec_type="OPT",
            priority=priority,
            subscribed_at=now,
        )

        self._active[contract.conId] = info
        self._contracts[contract.conId] = contract

        if priority == SubscriptionPriority.HIGH:
            self._priority_pins.add(contract.conId)

        self._log.info(
            "subscription.option_added",
            symbol=contract.symbol,
            con_id=contract.conId,
            active_count=self.active_count,
        )

        return ticker

    async def unsubscribe(self, con_id: int) -> bool:
        """Cancel a market data subscription.

        Removes the subscription from tracking and cancels the IB data line.

        Args:
            con_id: Contract ID of the subscription to cancel.

        Returns:
            True if subscription was found and cancelled, False otherwise.
        """
        if con_id not in self._active:
            return False

        contract = self._contracts.get(con_id)
        if contract is not None:
            self._ib.cancelMktData(contract)

        info = self._active.pop(con_id, None)
        self._contracts.pop(con_id, None)
        self._priority_pins.discard(con_id)

        # Remove from underlying map if this was an underlying
        if info is not None:
            keys_to_remove = [
                sym for sym, cid in self._underlying_map.items() if cid == con_id
            ]
            for sym in keys_to_remove:
                del self._underlying_map[sym]

        self._log.info(
            "subscription.removed",
            con_id=con_id,
        )

        return True

    def _evict_one(self) -> bool:
        """Evict the oldest non-pinned subscription (LRU policy).

        HIGH-priority subscriptions are pinned and never evicted.
        Among evictable subscriptions, the oldest (by subscribed_at) is removed.

        Returns:
            True if a subscription was evicted, False if none are evictable.
        """
        evictable = [
            (cid, info)
            for cid, info in self._active.items()
            if cid not in self._priority_pins
        ]

        if not evictable:
            self._log.warning("subscription.eviction_failed", reason="no_evictable")
            return False

        # Sort by subscribed_at ascending -- oldest first (LRU)
        evictable.sort(key=lambda x: x[1].subscribed_at)
        evict_id, evict_info = evictable[0]

        contract = self._contracts.get(evict_id)
        if contract is not None:
            self._ib.cancelMktData(contract)

        self._active.pop(evict_id, None)
        self._contracts.pop(evict_id, None)

        # Remove from underlying map if applicable
        keys_to_remove = [
            sym for sym, cid in self._underlying_map.items() if cid == evict_id
        ]
        for sym in keys_to_remove:
            del self._underlying_map[sym]

        self._log.info(
            "subscription.evicted",
            con_id=evict_id,
            symbol=evict_info.symbol,
        )

        return True

    def pin(self, con_id: int) -> None:
        """Pin a subscription so it cannot be evicted.

        Typically used for contracts with open positions.

        Args:
            con_id: Contract ID to pin.
        """
        self._priority_pins.add(con_id)

    def unpin(self, con_id: int) -> None:
        """Unpin a subscription, making it eligible for eviction.

        Args:
            con_id: Contract ID to unpin.
        """
        self._priority_pins.discard(con_id)

    def update_last_seen(self, con_id: int) -> None:
        """Update the last_update timestamp for a subscription.

        Called on every tick to track freshness for staleness detection.

        Args:
            con_id: Contract ID that received a tick update.
        """
        info = self._active.get(con_id)
        if info is not None:
            info.last_update = datetime.now(timezone.utc)
