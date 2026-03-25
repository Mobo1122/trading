"""Unit tests for IBConnectionManager.

Tests connection manager logic WITHOUT requiring a running IB Gateway.
All IB interactions are mocked. Tests verify:
  - Event handler attachment (once in constructor)
  - Initial state (disconnected, zero reconnect count)
  - Port selection based on trading mode
  - Shutdown prevents reconnection
  - Connected event callback sets state
  - Disconnected event callback schedules reconnection
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading.config import Settings
from trading.core.connection import IBConnectionManager


class MockEvent:
    """Mimics ib_async's Event class for tracking += handler attachment."""

    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def __isub__(self, handler):
        self.handlers.remove(handler)
        return self


@pytest.fixture
def mock_ib():
    """Create a mock IB instance with event handlers."""
    ib = MagicMock()
    ib.connectedEvent = MockEvent()
    ib.disconnectedEvent = MockEvent()
    ib.connectAsync = AsyncMock()
    ib.disconnect = MagicMock()
    return ib


@pytest.fixture
def manager(test_settings, mock_ib):
    """Create an IBConnectionManager with a mocked IB instance."""
    with patch("trading.core.connection.IB", return_value=mock_ib):
        mgr = IBConnectionManager(test_settings)
    return mgr


class TestManagerCreation:
    """Tests for IBConnectionManager initialization."""

    def test_manager_creation_attaches_handlers(self, test_settings, mock_ib):
        """Event handlers are attached exactly once in the constructor."""
        with patch("trading.core.connection.IB", return_value=mock_ib):
            mgr = IBConnectionManager(test_settings)

        assert len(mock_ib.connectedEvent.handlers) == 1
        assert len(mock_ib.disconnectedEvent.handlers) == 1
        assert mock_ib.connectedEvent.handlers[0] == mgr._on_connected
        assert mock_ib.disconnectedEvent.handlers[0] == mgr._on_disconnected

    def test_manager_initial_state(self, manager):
        """Manager starts disconnected with zero reconnect count."""
        assert manager.is_connected is False
        assert manager.reconnect_count == 0


class TestPortSelection:
    """Tests for trading mode to port mapping."""

    def test_port_selection_paper(self, manager, mock_ib):
        """Paper mode uses port 4002."""
        assert manager.settings.trading.ib_port == 4002

    def test_port_selection_live(self, mock_ib, monkeypatch):
        """Live mode uses port 4001."""
        monkeypatch.setenv("TRADING_MODE", "live")
        settings = Settings()
        with patch("trading.core.connection.IB", return_value=mock_ib):
            mgr = IBConnectionManager(settings)
        assert mgr.settings.trading.ib_port == 4001


class TestShutdown:
    """Tests for graceful shutdown behavior."""

    async def test_shutdown_prevents_reconnect(self, manager):
        """After disconnect(), _on_disconnected does NOT schedule reconnection."""
        await manager.disconnect()

        with patch("asyncio.create_task") as mock_create_task:
            manager._on_disconnected()

        mock_create_task.assert_not_called()

    async def test_disconnect_sets_shutdown_flag(self, manager):
        """disconnect() sets _shutdown to True."""
        assert manager._shutdown is False
        await manager.disconnect()
        assert manager._shutdown is True


class TestConnectedCallback:
    """Tests for the connected event handler."""

    def test_on_connected_sets_event(self, manager):
        """_on_connected sets is_connected to True and resets reconnect count."""
        manager._reconnect_count = 5
        manager._on_connected()
        assert manager.is_connected is True
        assert manager.reconnect_count == 0


class TestDisconnectedCallback:
    """Tests for the disconnected event handler."""

    def test_on_disconnected_schedules_reconnect(self, manager):
        """_on_disconnected schedules a reconnection task when not shutting down."""
        manager._connected.set()  # Simulate being connected first

        with patch("asyncio.create_task") as mock_create_task:
            manager._on_disconnected()

        assert manager.is_connected is False
        assert manager.reconnect_count == 1
        mock_create_task.assert_called_once()

    def test_on_disconnected_increments_count(self, manager):
        """Each disconnection increments the reconnect counter."""
        with patch("asyncio.create_task"):
            manager._on_disconnected()
            manager._on_disconnected()
            manager._on_disconnected()

        assert manager.reconnect_count == 3


class TestWaitConnected:
    """Tests for the wait_connected method."""

    async def test_wait_connected_returns_true_when_connected(self, manager):
        """wait_connected returns True when already connected."""
        manager._connected.set()
        result = await manager.wait_connected(timeout=1.0)
        assert result is True

    async def test_wait_connected_returns_false_on_timeout(self, manager):
        """wait_connected returns False when timeout expires."""
        result = await manager.wait_connected(timeout=0.05)
        assert result is False
