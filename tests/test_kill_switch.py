"""Unit tests for KillSwitch.

Tests emergency order cancellation and position liquidation logic
WITHOUT requiring a running IB Gateway. All IB interactions are mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from trading.kill_switch import KillSwitch


@pytest.fixture
def mock_ib():
    """Create a mock IB instance for kill switch tests."""
    ib = MagicMock()
    ib.reqGlobalCancel = MagicMock()
    ib.placeOrder = MagicMock()
    ib.positions = MagicMock(return_value=[])
    return ib


@pytest.fixture
def kill_switch(mock_ib):
    """Create a KillSwitch with a mocked IB instance."""
    return KillSwitch(mock_ib)


def _make_position(symbol: str, quantity: float):
    """Create a mock position with the given symbol and quantity."""
    position = MagicMock()
    position.position = quantity
    position.contract = MagicMock()
    position.contract.symbol = symbol
    return position


class TestCancelAllOrders:
    """Tests for cancel_all_orders method."""

    async def test_cancel_all_orders(self, kill_switch, mock_ib):
        """reqGlobalCancel is called to cancel all open orders."""
        await kill_switch.cancel_all_orders()
        mock_ib.reqGlobalCancel.assert_called_once()


class TestCloseAllPositions:
    """Tests for close_all_positions method."""

    async def test_close_long_position(self, kill_switch, mock_ib):
        """Long position generates a SELL market order."""
        mock_ib.positions.return_value = [_make_position("AAPL", 100)]

        count = await kill_switch.close_all_positions()

        assert count == 1
        mock_ib.placeOrder.assert_called_once()
        args = mock_ib.placeOrder.call_args
        contract = args[0][0]
        order = args[0][1]
        assert contract.symbol == "AAPL"
        assert order.action == "SELL"
        assert order.totalQuantity == 100

    async def test_close_short_position(self, kill_switch, mock_ib):
        """Short position generates a BUY market order."""
        mock_ib.positions.return_value = [_make_position("SPY", -50)]

        count = await kill_switch.close_all_positions()

        assert count == 1
        args = mock_ib.placeOrder.call_args
        order = args[0][1]
        assert order.action == "BUY"
        assert order.totalQuantity == 50

    async def test_skips_zero_position(self, kill_switch, mock_ib):
        """Zero-quantity positions are skipped (no order placed)."""
        mock_ib.positions.return_value = [_make_position("MSFT", 0)]

        count = await kill_switch.close_all_positions()

        assert count == 0
        mock_ib.placeOrder.assert_not_called()

    async def test_close_multiple_positions(self, kill_switch, mock_ib):
        """Multiple positions each generate a closing order."""
        mock_ib.positions.return_value = [
            _make_position("AAPL", 100),
            _make_position("SPY", -50),
            _make_position("MSFT", 0),  # skipped
        ]

        count = await kill_switch.close_all_positions()

        assert count == 2
        assert mock_ib.placeOrder.call_count == 2

    async def test_cancels_orders_before_closing(self, kill_switch, mock_ib):
        """cancel_all_orders is called before placing closing orders."""
        mock_ib.positions.return_value = [_make_position("AAPL", 100)]

        call_order = []
        mock_ib.reqGlobalCancel.side_effect = lambda: call_order.append("cancel")
        mock_ib.placeOrder.side_effect = lambda *a: call_order.append("place")

        await kill_switch.close_all_positions()

        assert call_order == ["cancel", "place"]


class TestEmergencyShutdown:
    """Tests for emergency_shutdown method."""

    async def test_emergency_shutdown_cancels_then_closes(self, kill_switch, mock_ib):
        """Emergency shutdown cancels all orders and closes all positions."""
        mock_ib.positions.return_value = [
            _make_position("AAPL", 100),
            _make_position("GOOG", -25),
        ]

        count = await kill_switch.emergency_shutdown()

        assert count == 2
        mock_ib.reqGlobalCancel.assert_called_once()
        assert mock_ib.placeOrder.call_count == 2
