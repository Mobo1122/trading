"""Staleness detection for market data subscriptions.

Periodically checks all active subscriptions for data freshness.
Subscriptions that have not received updates beyond the configured
threshold (default: 30 seconds during market hours) are flagged
as stale via Redis pub/sub notification.

This enables downstream consumers (risk engine, agents) to detect
and react to data quality issues in real time.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog

from trading.config import Settings
from trading.market_data.distributor import RedisDistributor
from trading.market_data.subscriber import SubscriptionManager


class StalenessMonitor:
    """Monitors market data subscriptions for staleness.

    Runs a periodic check (every 10 seconds) that compares each
    subscription's last_update timestamp against the staleness threshold.
    Stale subscriptions are reported via the RedisDistributor's
    staleness channel.

    Args:
        subscriber: SubscriptionManager providing active subscription state.
        distributor: RedisDistributor for publishing staleness alerts.
        settings: Application settings (reads staleness threshold).
    """

    def __init__(
        self,
        subscriber: SubscriptionManager,
        distributor: RedisDistributor,
        settings: Settings,
    ) -> None:
        self._subscriber = subscriber
        self._distributor = distributor
        self._threshold: int = settings.market_data.staleness_threshold_seconds

        self._check_task: asyncio.Task | None = None
        self._running: bool = False

        self._log = structlog.get_logger().bind(
            component="staleness_monitor",
        )

    async def start(self) -> None:
        """Start the periodic staleness check loop."""
        self._running = True
        self._check_task = asyncio.create_task(self._check_loop())
        self._log.info(
            "staleness.started",
            threshold_seconds=self._threshold,
        )

    async def stop(self) -> None:
        """Stop the staleness check loop."""
        self._running = False

        if self._check_task is not None:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
            self._check_task = None

        self._log.info("staleness.stopped")

    async def _check_loop(self) -> None:
        """Periodic loop that checks all subscriptions for staleness.

        Runs every 10 seconds. Wraps the check in try/except to
        prevent task death on transient errors.
        """
        while self._running:
            try:
                await asyncio.sleep(10)
                await self._check_all()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._log.warning(
                    "staleness.check_loop_error",
                    error=str(e),
                )

    async def _check_all(self) -> None:
        """Check all active subscriptions for staleness.

        For each subscription, compares the time since last update
        (or since subscription if no update has ever arrived) against
        the staleness threshold. Stale subscriptions are published
        to the staleness channel.
        """
        now = datetime.now(timezone.utc)

        for con_id, info in self._subscriber.active_subscriptions.items():
            check_time = info.last_update if info.last_update else info.subscribed_at

            # Ensure timezone-aware comparison
            if check_time.tzinfo is None:
                check_time = check_time.replace(tzinfo=timezone.utc)

            seconds = (now - check_time).total_seconds()

            if seconds > self._threshold:
                await self._distributor.publish_stale(
                    con_id,
                    info.symbol,
                    seconds,
                )
                self._log.warning(
                    "staleness.detected",
                    con_id=con_id,
                    symbol=info.symbol,
                    seconds_since_update=round(seconds, 1),
                )
