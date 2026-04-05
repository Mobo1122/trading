"""Tests for FillTracker -> CircuitBreaker loss accumulation wiring.

Verifies that realized losses from filled trades are routed to the
circuit breaker for daily/weekly loss-limit tracking.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading.orders.fill_tracker import FillTracker


@pytest.fixture
def mock_session_factory():
    """Mock session factory with async context manager support."""
    factory = MagicMock()
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    factory.return_value = session
    return factory, session


@pytest.fixture
def tracker(mock_session_factory):
    """Create FillTracker with mock session."""
    factory, _ = mock_session_factory
    return FillTracker(session_factory=factory)


def _make_fill(exec_id: str = "exec-001"):
    """Create a mock Fill object."""
    fill = MagicMock()
    fill.execution.execId = exec_id
    return fill


def _make_commission_report(realized_pnl: float, commission: float = 1.25):
    """Create a mock CommissionReport."""
    report = MagicMock()
    report.realizedPNL = realized_pnl
    report.commission = commission
    return report


def _mock_session_for_commission(session, realized_pnl: float):
    """Set up session mocks for record_commission (exec_record + order queries)."""
    exec_record = MagicMock()
    exec_record.commission = None
    exec_record.realized_pnl = None

    mock_order = MagicMock()
    mock_order.total_commission = 0.0

    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = exec_record
    order_result = MagicMock()
    order_result.scalar_one_or_none.return_value = mock_order

    session.execute = AsyncMock(side_effect=[exec_result, order_result])
    return exec_record, mock_order


class TestFillTrackerCircuitBreaker:
    """Tests for circuit breaker wiring in FillTracker."""

    @pytest.mark.asyncio
    async def test_record_commission_routes_loss_to_circuit_breaker(
        self, tracker, mock_session_factory
    ):
        """Negative realizedPNL triggers circuit_breaker.record_realized_loss."""
        _, session = mock_session_factory
        _mock_session_for_commission(session, -150.0)

        mock_cb = AsyncMock()
        tracker.circuit_breaker = mock_cb

        fill = _make_fill()
        report = _make_commission_report(realized_pnl=-150.0)
        trade = MagicMock()

        with patch("trading.orders.fill_tracker.get_session") as mock_gs:
            mock_gs.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_gs.return_value.__aexit__ = AsyncMock(return_value=False)
            await tracker.record_commission("order-001", trade, fill, report)

        mock_cb.record_realized_loss.assert_awaited_once_with(150.0)

    @pytest.mark.asyncio
    async def test_record_commission_ignores_profit(
        self, tracker, mock_session_factory
    ):
        """Positive realizedPNL does NOT call circuit_breaker.record_realized_loss."""
        _, session = mock_session_factory
        _mock_session_for_commission(session, 200.0)

        mock_cb = AsyncMock()
        tracker.circuit_breaker = mock_cb

        fill = _make_fill()
        report = _make_commission_report(realized_pnl=200.0)
        trade = MagicMock()

        with patch("trading.orders.fill_tracker.get_session") as mock_gs:
            mock_gs.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_gs.return_value.__aexit__ = AsyncMock(return_value=False)
            await tracker.record_commission("order-001", trade, fill, report)

        mock_cb.record_realized_loss.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_record_commission_handles_no_circuit_breaker(
        self, tracker, mock_session_factory
    ):
        """No crash when _circuit_breaker is None and a loss arrives."""
        _, session = mock_session_factory
        _mock_session_for_commission(session, -50.0)

        # circuit_breaker is None by default
        assert tracker.circuit_breaker is None

        fill = _make_fill()
        report = _make_commission_report(realized_pnl=-50.0)
        trade = MagicMock()

        with patch("trading.orders.fill_tracker.get_session") as mock_gs:
            mock_gs.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_gs.return_value.__aexit__ = AsyncMock(return_value=False)
            # Should NOT raise
            await tracker.record_commission("order-001", trade, fill, report)

    @pytest.mark.asyncio
    async def test_apply_commission_routes_loss_to_circuit_breaker(
        self, tracker, mock_session_factory
    ):
        """Buffered commission path also routes losses to circuit breaker."""
        _, session = mock_session_factory
        _mock_session_for_commission(session, -75.0)

        mock_cb = AsyncMock()
        tracker.circuit_breaker = mock_cb

        report = _make_commission_report(realized_pnl=-75.0)

        with patch("trading.orders.fill_tracker.get_session") as mock_gs:
            mock_gs.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_gs.return_value.__aexit__ = AsyncMock(return_value=False)
            await tracker._apply_commission("order-001", "exec-001", report)

        mock_cb.record_realized_loss.assert_awaited_once_with(75.0)
