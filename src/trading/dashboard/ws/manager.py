"""WebSocket channel subscription manager.

Tracks WebSocket connections per channel and provides broadcast
capabilities with automatic dead connection cleanup.
"""

from __future__ import annotations

import structlog
from fastapi import WebSocket


class ChannelManager:
    """Manages WebSocket subscriptions per channel.

    Maintains a bidirectional mapping between channels and WebSocket
    connections for efficient subscribe/unsubscribe/broadcast operations.
    Dead connections detected during broadcast are automatically cleaned up.
    """

    def __init__(self) -> None:
        self._subscriptions: dict[str, set[WebSocket]] = {}
        self._ws_channels: dict[WebSocket, set[str]] = {}
        self._log = structlog.get_logger().bind(component="channel_manager")

    async def subscribe(self, ws: WebSocket, channel: str) -> None:
        """Subscribe a WebSocket connection to a channel.

        Args:
            ws: The WebSocket connection to subscribe.
            channel: Channel name to subscribe to.
        """
        if channel not in self._subscriptions:
            self._subscriptions[channel] = set()
        self._subscriptions[channel].add(ws)

        if ws not in self._ws_channels:
            self._ws_channels[ws] = set()
        self._ws_channels[ws].add(channel)

        self._log.debug(
            "ws.subscribed",
            channel=channel,
            subscribers=len(self._subscriptions[channel]),
        )

    async def unsubscribe(self, ws: WebSocket, channel: str) -> None:
        """Unsubscribe a WebSocket connection from a channel.

        Args:
            ws: The WebSocket connection to unsubscribe.
            channel: Channel name to unsubscribe from.
        """
        if channel in self._subscriptions:
            self._subscriptions[channel].discard(ws)
            if not self._subscriptions[channel]:
                del self._subscriptions[channel]

        if ws in self._ws_channels:
            self._ws_channels[ws].discard(channel)
            if not self._ws_channels[ws]:
                del self._ws_channels[ws]

        self._log.debug("ws.unsubscribed", channel=channel)

    async def unsubscribe_all(self, ws: WebSocket) -> None:
        """Remove a WebSocket connection from all channels.

        Used during disconnect cleanup to ensure no dangling references.

        Args:
            ws: The WebSocket connection to remove.
        """
        channels = self._ws_channels.pop(ws, set())
        for channel in channels:
            if channel in self._subscriptions:
                self._subscriptions[channel].discard(ws)
                if not self._subscriptions[channel]:
                    del self._subscriptions[channel]

        if channels:
            self._log.debug(
                "ws.unsubscribed_all",
                channels_removed=len(channels),
            )

    async def broadcast(self, channel: str, message: str) -> None:
        """Send a message to all subscribers of a channel.

        Dead connections (those that raise on send) are collected and
        cleaned up after the broadcast loop completes.

        Args:
            channel: Channel to broadcast to.
            message: JSON string message to send.
        """
        subscribers = self._subscriptions.get(channel)
        if not subscribers:
            return

        dead: list[WebSocket] = []
        for ws in subscribers:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self._log.debug("ws.dead_connection_removed", channel=channel)
            await self.unsubscribe_all(ws)

    @property
    def active_connections(self) -> int:
        """Total number of unique WebSocket connections across all channels."""
        return len(self._ws_channels)
