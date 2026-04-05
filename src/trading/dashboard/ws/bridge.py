"""Redis pub/sub to WebSocket bridge.

Subscribes to Redis pub/sub channels for market data and dashboard
updates, maps them to dashboard topic names, and broadcasts to
WebSocket clients via the ChannelManager. Includes per-channel
throttling to prevent flooding clients with high-frequency ticks.
"""

from __future__ import annotations

import asyncio
import json
import time

import structlog
from redis.asyncio import Redis

from trading.dashboard.ws.manager import ChannelManager


class RedisBridge:
    """Bridges Redis pub/sub channels to WebSocket clients.

    Subscribes to market data and dashboard Redis channels using
    pattern subscriptions. Maps Redis channel names to dashboard
    topic names and broadcasts updates via ChannelManager.

    Update throttling batches incoming messages per channel, flushing
    every throttle_ms milliseconds. Only the latest message per channel
    is kept, preventing flooding from high-frequency market data ticks.

    Args:
        redis: Async Redis client instance.
        channel_manager: ChannelManager for broadcasting to WebSocket clients.
        throttle_ms: Milliseconds between batched updates (default 500).
    """

    CHANNELS: list[str] = [
        "mktdata:quote:*",
        "mktdata:greeks:*",
        "mktdata:stale",
        "dashboard:positions",
        "dashboard:health",
        "dashboard:portfolio_greeks",
    ]

    def __init__(
        self,
        redis: Redis,
        channel_manager: ChannelManager,
        throttle_ms: int = 500,
    ) -> None:
        self._redis = redis
        self._channel_manager = channel_manager
        self._throttle_ms = throttle_ms
        self._pending: dict[str, str] = {}
        self._flush_task: asyncio.Task | None = None
        self._log = structlog.get_logger().bind(component="redis_bridge")

    async def listen(self) -> None:
        """Subscribe to Redis channels and forward messages to WebSocket clients.

        Runs indefinitely until cancelled. On cancellation, cleanly
        unsubscribes and closes the pubsub connection.
        """
        pubsub = self._redis.pubsub()
        try:
            await pubsub.psubscribe(*self.CHANNELS)
            self._log.info(
                "redis_bridge.subscribed",
                channels=self.CHANNELS,
            )

            # Start the flush timer
            self._flush_task = asyncio.create_task(self._flush_loop())

            async for message in pubsub.listen():
                if message["type"] != "pmessage":
                    continue

                redis_channel = message["channel"]
                if isinstance(redis_channel, bytes):
                    redis_channel = redis_channel.decode()

                topic = self._map_channel(redis_channel)
                if topic is None:
                    continue

                # Parse data payload
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode()

                try:
                    parsed = json.loads(data) if isinstance(data, str) else data
                except (json.JSONDecodeError, TypeError):
                    parsed = data

                envelope = json.dumps({
                    "type": "update",
                    "channel": topic,
                    "data": parsed,
                })

                # Buffer the latest message per topic for throttled flush
                self._pending[topic] = envelope

        except asyncio.CancelledError:
            self._log.info("redis_bridge.shutting_down")
            if self._flush_task is not None:
                self._flush_task.cancel()
                try:
                    await self._flush_task
                except asyncio.CancelledError:
                    pass
            try:
                await pubsub.punsubscribe()
                await pubsub.close()
            except Exception:
                pass
            raise
        except Exception:
            self._log.error("redis_bridge.listen_error", exc_info=True)
            if self._flush_task is not None:
                self._flush_task.cancel()
                try:
                    await self._flush_task
                except asyncio.CancelledError:
                    pass
            raise

    async def _flush_loop(self) -> None:
        """Periodically flush pending messages to WebSocket clients.

        Runs every throttle_ms milliseconds, broadcasting the latest
        buffered message for each topic and clearing the buffer.
        """
        interval = self._throttle_ms / 1000.0
        try:
            while True:
                await asyncio.sleep(interval)
                if not self._pending:
                    continue

                # Swap buffer atomically
                to_send = self._pending
                self._pending = {}

                for topic, envelope in to_send.items():
                    try:
                        await self._channel_manager.broadcast(topic, envelope)
                    except Exception:
                        self._log.warning(
                            "redis_bridge.broadcast_failed",
                            topic=topic,
                            exc_info=True,
                        )
        except asyncio.CancelledError:
            # Final flush of any remaining messages
            for topic, envelope in self._pending.items():
                try:
                    await self._channel_manager.broadcast(topic, envelope)
                except Exception:
                    pass
            raise

    def _map_channel(self, redis_channel: str) -> str | None:
        """Map a Redis channel name to a dashboard topic name.

        Args:
            redis_channel: The Redis pub/sub channel name.

        Returns:
            Dashboard topic name, or None if channel is unknown.
        """
        if redis_channel.startswith("mktdata:quote:"):
            symbol = redis_channel[len("mktdata:quote:"):]
            return f"quotes:{symbol}"

        if redis_channel.startswith("mktdata:greeks:"):
            suffix = redis_channel[len("mktdata:greeks:"):]
            return f"greeks:{suffix}"

        if redis_channel == "mktdata:stale":
            return "staleness"

        if redis_channel == "dashboard:positions":
            return "positions"

        if redis_channel == "dashboard:health":
            return "health"

        if redis_channel == "dashboard:portfolio_greeks":
            return "portfolio_greeks"

        return None
