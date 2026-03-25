"""IB Gateway connection manager with automatic reconnection.

This module provides the single point of contact between the trading system
and Interactive Brokers. Every IB API interaction (market data, orders,
contracts) flows through the IBConnectionManager.

Key design decisions:
  - Event handlers attached ONCE in constructor (never during reconnection)
  - Single IB() instance for entire app lifecycle (never per-request)
  - Exponential backoff with jitter on reconnection
  - Graceful shutdown prevents reconnection attempts
  - Connection state observable via asyncio.Event
"""

from __future__ import annotations

import asyncio
import random

import structlog
from ib_async import IB

from trading.config import Settings

logger = structlog.get_logger()


class IBConnectionManager:
    """Manages the IB Gateway connection with auto-reconnect.

    This manager maintains a single IB() instance and handles:
      - Initial connection with retry
      - Automatic reconnection on disconnection (e.g., IB daily restart)
      - Exponential backoff with jitter to avoid thundering herd
      - Graceful shutdown that prevents further reconnection attempts
      - Observable connection state via asyncio.Event

    Usage:
        settings = Settings()
        manager = IBConnectionManager(settings)
        await manager.connect()
        await manager.wait_connected()
        # ... use manager.ib for API calls ...
        await manager.disconnect()
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.ib = IB()
        self._connected = asyncio.Event()
        self._shutdown = False
        self._reconnect_count = 0
        self._log = logger.bind(
            component="ib_connection",
            mode=settings.trading.mode,
        )

        # Attach event handlers EXACTLY ONCE here.
        # CRITICAL: Never attach handlers during reconnection (Pitfall 2).
        self.ib.connectedEvent += self._on_connected
        self.ib.disconnectedEvent += self._on_disconnected

    async def connect(self) -> None:
        """Public entry point for initial connection.

        Logs the connection attempt with mode and target, then
        delegates to the reconnection loop.
        """
        self._log.info(
            "ib.connect_start",
            host=self.settings.ib.host,
            port=self.settings.trading.ib_port,
        )
        await self._do_connect()

    async def _do_connect(self) -> None:
        """Connect with exponential backoff and jitter.

        Retries until connected or shutdown is requested.
        Respects max_reconnect_attempts if > 0 (0 = infinite).
        """
        attempt = 0
        max_attempts = self.settings.ib.max_reconnect_attempts

        while not self._shutdown:
            try:
                await self.ib.connectAsync(
                    host=self.settings.ib.host,
                    port=self.settings.trading.ib_port,
                    clientId=self.settings.ib.client_id,
                    timeout=self.settings.ib.timeout,
                )
                self._connected.set()
                self._log.info(
                    "ib.connected",
                    port=self.settings.trading.ib_port,
                )
                return
            except Exception as e:
                attempt += 1

                if max_attempts > 0 and attempt >= max_attempts:
                    self._log.error(
                        "ib.max_reconnect_attempts_reached",
                        attempts=attempt,
                        error=str(e),
                    )
                    return

                delay = min(
                    self.settings.ib.reconnect_delay * (2 ** attempt),
                    self.settings.ib.reconnect_max_delay,
                )
                # Add jitter (0-1 second) to avoid thundering herd
                jitter = random.random()
                delay += jitter

                self._log.warning(
                    "ib.connect_failed",
                    attempt=attempt,
                    error=str(e),
                    retry_in=round(delay, 2),
                )
                await asyncio.sleep(delay)

    def _on_connected(self) -> None:
        """Handle IB connected event.

        Sets the connected event and resets the reconnect counter.
        """
        self._connected.set()
        self._reconnect_count = 0
        self._log.info("ib.connected")

    def _on_disconnected(self) -> None:
        """Handle IB disconnected event.

        If not shutting down, increments reconnect count and
        schedules a reconnection task. If shutting down, just logs.
        """
        self._connected.clear()

        if not self._shutdown:
            self._reconnect_count += 1
            self._log.warning(
                "ib.disconnected",
                reconnect_count=self._reconnect_count,
            )
            asyncio.create_task(self._do_connect())
        else:
            self._log.info("ib.disconnected", reason="shutdown")

    async def disconnect(self) -> None:
        """Graceful shutdown: stop reconnection attempts and disconnect.

        Sets the shutdown flag first to prevent _on_disconnected from
        scheduling a reconnection, then disconnects.
        """
        self._shutdown = True
        self.ib.disconnect()
        self._log.info("ib.shutdown_complete")

    async def wait_connected(self, timeout: float | None = None) -> bool:
        """Wait for the connection to be established.

        Args:
            timeout: Maximum seconds to wait. None means wait forever.

        Returns:
            True if connected, False if timeout expired.
        """
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    @property
    def is_connected(self) -> bool:
        """Whether the IB connection is currently active."""
        return self._connected.is_set()

    @property
    def reconnect_count(self) -> int:
        """Number of reconnection attempts since last successful connection."""
        return self._reconnect_count
