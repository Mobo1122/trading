"""Comprehensive tests for Phase 4 order execution components.

Covers:
- calculate_slippage: All directions and edge cases
- ComboOrderBuilder: build_bag, build_from_trade_legs, routing, validation
- OrderExecutionService: risk gate, single-leg, multi-leg, cancel
- FillTracker: fill recording, slippage, duplicate handling
- OrderRecoveryManager: recover open, filled, and missing orders

All tests use mocks -- NO real IB connection or database.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ib_async import Bag, ComboLeg, LimitOrder, MarketOrder, Option, TagValue

from trading.orders.combo_builder import ComboOrderBuilder
from trading.orders.execution_service import OrderExecutionService
from trading.orders.fill_tracker import FillTracker
from trading.orders.models import SlippageReport, calculate_slippage
from trading.orders.recovery import OrderRecoveryManager
from trading.orders.state_machine import OrderStateMachine
from trading.orders.tracker import OrderTracker
from trading.risk.models import (
    GreeksImpact,
    RiskDecision,
    TradeLeg,
    TradeProposal,
    ViolatedRule,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def make_proposal(**kwargs) -> TradeProposal:
    """Create a test TradeProposal with sensible defaults."""
    defaults = {
        "legs": [TradeLeg(symbol="SPY", sec_type="OPT", action="BUY", quantity=2)],
        "estimated_greeks": GreeksImpact(delta=50, gamma=5, theta=-10, vega=20),
        "max_loss": 1000.0,
        "strategy_type": "vertical_spread",
        "account_value": 100_000.0,
    }
    defaults.update(kwargs)
    return TradeProposal(**defaults)


def make_mock_contract(con_id: int = 12345) -> MagicMock:
    """Create a mock IB contract with conId."""
    contract = MagicMock()
    contract.conId = con_id
    return contract


def make_mock_trade(order_id: int = 1, perm_id: int = 100, status: str = "Submitted") -> MagicMock:
    """Create a mock IB Trade object."""
    trade = MagicMock()
    trade.order.orderId = order_id
    trade.order.permId = perm_id
    trade.orderStatus.status = status
    trade.isDone.return_value = False
    # Event attributes for subscription
    trade.statusEvent = MagicMock()
    trade.fillEvent = MagicMock()
    trade.commissionReportEvent = MagicMock()
    return trade


# ============================================================================
# calculate_slippage Tests
# ============================================================================


class TestCalculateSlippage:
    """Tests for the calculate_slippage utility function."""

    def test_buy_unfavorable(self):
        """BUY at higher than expected is unfavorable (positive slippage)."""
        dollars, bps = calculate_slippage(
            action="BUY", expected_price=5.00, fill_price=5.10, quantity=10
        )
        assert dollars == 1.0  # (5.10 - 5.00) * 10
        assert bps == 200.0  # ((5.10 - 5.00) / 5.00) * 10000

    def test_buy_favorable(self):
        """BUY at lower than expected is favorable (negative slippage)."""
        dollars, bps = calculate_slippage(
            action="BUY", expected_price=5.00, fill_price=4.90, quantity=10
        )
        assert dollars == -1.0  # (4.90 - 5.00) * 10
        assert bps == -200.0

    def test_sell_unfavorable(self):
        """SELL at lower than expected is unfavorable (positive slippage)."""
        dollars, bps = calculate_slippage(
            action="SELL", expected_price=5.00, fill_price=4.90, quantity=10
        )
        assert dollars == 1.0  # (5.00 - 4.90) * 10
        assert bps == 200.0  # -((4.90 - 5.00) / 5.00) * 10000

    def test_sell_favorable(self):
        """SELL at higher than expected is favorable (negative slippage)."""
        dollars, bps = calculate_slippage(
            action="SELL", expected_price=5.00, fill_price=5.10, quantity=10
        )
        assert dollars == -1.0  # (5.00 - 5.10) * 10
        assert bps == -200.0

    def test_zero_expected_price(self):
        """Zero expected price yields 0 bps to avoid division by zero."""
        dollars, bps = calculate_slippage(
            action="BUY", expected_price=0.0, fill_price=1.00, quantity=5
        )
        assert dollars == 5.0  # (1.00 - 0.00) * 5
        assert bps == 0.0

    def test_exact_fill(self):
        """Fill at exactly expected price means zero slippage."""
        dollars, bps = calculate_slippage(
            action="BUY", expected_price=5.00, fill_price=5.00, quantity=10
        )
        assert dollars == 0.0
        assert bps == 0.0


# ============================================================================
# ComboOrderBuilder Tests
# ============================================================================


class TestComboOrderBuilder:
    """Tests for ComboOrderBuilder BAG contract construction."""

    def test_build_bag_single_leg(self):
        """Build a bag with a single leg."""
        bag = ComboOrderBuilder.build_bag(
            symbol="SPY",
            legs=[{"conId": 111, "ratio": 1, "action": "BUY"}],
        )
        assert isinstance(bag, Bag)
        assert bag.symbol == "SPY"
        assert bag.exchange == "SMART"
        assert len(bag.comboLegs) == 1
        assert bag.comboLegs[0].conId == 111

    def test_build_bag_two_legs_vertical(self):
        """Build a vertical spread (2 legs)."""
        bag = ComboOrderBuilder.build_bag(
            symbol="AAPL",
            legs=[
                {"conId": 111, "ratio": 1, "action": "BUY"},
                {"conId": 222, "ratio": 1, "action": "SELL"},
            ],
        )
        assert len(bag.comboLegs) == 2
        assert bag.comboLegs[0].action == "BUY"
        assert bag.comboLegs[1].action == "SELL"

    def test_build_bag_four_legs_iron_condor(self):
        """Build an iron condor (4 legs)."""
        legs = [
            {"conId": i, "ratio": 1, "action": "BUY" if i % 2 == 0 else "SELL"}
            for i in range(1, 5)
        ]
        bag = ComboOrderBuilder.build_bag(symbol="SPY", legs=legs)
        assert len(bag.comboLegs) == 4

    def test_build_bag_six_legs_max(self):
        """Build with 6 legs (IB maximum)."""
        legs = [
            {"conId": i, "ratio": 1, "action": "BUY"} for i in range(1, 7)
        ]
        bag = ComboOrderBuilder.build_bag(symbol="SPY", legs=legs)
        assert len(bag.comboLegs) == 6

    def test_empty_legs_raises(self):
        """Empty legs list raises ValueError."""
        with pytest.raises(ValueError, match="At least one leg"):
            ComboOrderBuilder.build_bag(symbol="SPY", legs=[])

    def test_seven_legs_raises(self):
        """More than 6 legs raises ValueError."""
        legs = [
            {"conId": i, "ratio": 1, "action": "BUY"} for i in range(1, 8)
        ]
        with pytest.raises(ValueError, match="Maximum 6 legs"):
            ComboOrderBuilder.build_bag(symbol="SPY", legs=legs)

    def test_build_from_trade_legs(self):
        """Build bag from TradeLeg objects with qualified contracts."""
        contract1 = make_mock_contract(con_id=111)
        contract2 = make_mock_contract(con_id=222)
        trade_legs = [
            TradeLeg(
                symbol="SPY", sec_type="OPT", action="BUY", quantity=1,
                contract=contract1,
            ),
            TradeLeg(
                symbol="SPY", sec_type="OPT", action="SELL", quantity=1,
                contract=contract2,
            ),
        ]
        bag = ComboOrderBuilder.build_from_trade_legs(
            symbol="SPY", trade_legs=trade_legs
        )
        assert isinstance(bag, Bag)
        assert len(bag.comboLegs) == 2
        assert bag.comboLegs[0].conId == 111
        assert bag.comboLegs[1].conId == 222

    def test_build_from_trade_legs_missing_contract(self):
        """TradeLeg without contract raises ValueError."""
        trade_legs = [
            TradeLeg(symbol="SPY", sec_type="OPT", action="BUY", quantity=1),
        ]
        with pytest.raises(ValueError, match="missing qualified contract"):
            ComboOrderBuilder.build_from_trade_legs(
                symbol="SPY", trade_legs=trade_legs
            )

    def test_apply_combo_routing(self):
        """apply_combo_routing sets NonGuaranteed tag on order."""
        order = MarketOrder("BUY", 1)
        ComboOrderBuilder.apply_combo_routing(order)
        assert order.smartComboRoutingParams is not None
        assert len(order.smartComboRoutingParams) == 1
        tag = order.smartComboRoutingParams[0]
        assert tag.tag == "NonGuaranteed"
        assert tag.value == "1"


# ============================================================================
# OrderExecutionService Tests
# ============================================================================


class TestOrderExecutionService:
    """Tests for risk-gated order submission."""

    @pytest.fixture
    def mock_ib(self):
        """Mock IB connection."""
        ib = MagicMock()
        trade = make_mock_trade()
        ib.placeOrder.return_value = trade
        return ib

    @pytest.fixture
    def mock_risk_manager(self):
        """Mock RiskManager."""
        return AsyncMock()

    @pytest.fixture
    def mock_order_tracker(self):
        """Mock OrderTracker."""
        tracker = MagicMock(spec=OrderTracker)
        tracker.create_order = MagicMock()
        tracker.transition = AsyncMock()
        return tracker

    @pytest.fixture
    def mock_session_factory(self):
        """Mock session factory with async context manager."""
        factory = MagicMock()
        session = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.close = AsyncMock()

        # Mock the Order returned from flush to have an id
        mock_order = MagicMock()
        mock_order.id = "test-order-id-1234"
        session.add.side_effect = lambda obj: setattr(obj, "id", "test-order-id-1234")

        factory.return_value = session
        return factory

    @pytest.fixture
    def service(self, mock_ib, mock_risk_manager, mock_order_tracker, mock_session_factory):
        """Create OrderExecutionService with all mocks."""
        return OrderExecutionService(
            ib=mock_ib,
            risk_manager=mock_risk_manager,
            order_tracker=mock_order_tracker,
            session_factory=mock_session_factory,
        )

    @pytest.mark.asyncio
    async def test_submit_order_risk_rejected(self, service, mock_ib):
        """Rejected proposal never reaches IB placeOrder."""
        proposal = make_proposal()
        rejection = RiskDecision(
            approved=False,
            violated_rule=ViolatedRule.POSITION_SIZE_DOLLARS,
            details="Exceeds position limit",
            proposal_id=proposal.proposal_id,
        )

        with patch(
            "trading.orders.execution_service.evaluate_with_failsafe",
            new_callable=AsyncMock,
            return_value=rejection,
        ):
            decision, trade = await service.submit_order(proposal)

        assert decision.approved is False
        assert decision.violated_rule == ViolatedRule.POSITION_SIZE_DOLLARS
        assert trade is None
        mock_ib.placeOrder.assert_not_called()

    @pytest.mark.asyncio
    async def test_submit_order_risk_approved_single_leg(self, service, mock_ib, mock_order_tracker):
        """Approved single-leg proposal places order via IB."""
        contract = make_mock_contract()
        order = MarketOrder("BUY", 2)
        proposal = make_proposal(
            legs=[
                TradeLeg(
                    symbol="SPY", sec_type="OPT", action="BUY", quantity=2,
                    contract=contract, order=order,
                ),
            ]
        )
        approval = RiskDecision(
            approved=True,
            proposal_id=proposal.proposal_id,
        )

        with patch(
            "trading.orders.execution_service.evaluate_with_failsafe",
            new_callable=AsyncMock,
            return_value=approval,
        ):
            decision, trade = await service.submit_order(proposal)

        assert decision.approved is True
        assert trade is not None
        mock_ib.placeOrder.assert_called_once()
        mock_order_tracker.create_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_submit_order_multi_leg(self, service, mock_ib, mock_order_tracker):
        """Multi-leg proposal constructs a Bag contract."""
        contract1 = make_mock_contract(con_id=111)
        contract2 = make_mock_contract(con_id=222)
        proposal = make_proposal(
            legs=[
                TradeLeg(
                    symbol="SPY", sec_type="OPT", action="BUY", quantity=1,
                    contract=contract1,
                ),
                TradeLeg(
                    symbol="SPY", sec_type="OPT", action="SELL", quantity=1,
                    contract=contract2,
                ),
            ]
        )
        approval = RiskDecision(
            approved=True,
            proposal_id=proposal.proposal_id,
        )

        with patch(
            "trading.orders.execution_service.evaluate_with_failsafe",
            new_callable=AsyncMock,
            return_value=approval,
        ):
            decision, trade = await service.submit_order(proposal)

        assert decision.approved is True
        assert trade is not None
        mock_ib.placeOrder.assert_called_once()
        # Verify the first arg was a Bag contract
        placed_contract = mock_ib.placeOrder.call_args[0][0]
        assert isinstance(placed_contract, Bag)
        assert len(placed_contract.comboLegs) == 2

    @pytest.mark.asyncio
    async def test_cancel_order(self, service, mock_ib, mock_order_tracker):
        """Cancel flow transitions state and sends IB cancel."""
        trade = make_mock_trade()
        service._active_trades["order-123"] = trade

        result = await service.cancel_order("order-123")

        assert result is trade
        mock_order_tracker.transition.assert_called_once_with(
            "order-123", "request_cancel"
        )
        mock_ib.cancelOrder.assert_called_once_with(trade.order)


# ============================================================================
# FillTracker Tests
# ============================================================================


class TestFillTracker:
    """Tests for fill recording and slippage measurement."""

    @pytest.fixture
    def mock_session_factory(self):
        """Mock session factory for FillTracker."""
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
    def tracker(self, mock_session_factory):
        """Create FillTracker with mock session."""
        factory, _ = mock_session_factory
        return FillTracker(session_factory=factory)

    def _make_fill(self, exec_id: str = "exec-001", price: float = 5.10, shares: float = 10):
        """Create a mock Fill object."""
        fill = MagicMock()
        fill.execution.execId = exec_id
        fill.execution.side = "BOT"
        fill.execution.shares = shares
        fill.execution.price = price
        fill.execution.avgPrice = price
        fill.execution.cumQty = shares
        fill.execution.exchange = "SMART"
        fill.execution.permId = 100
        return fill

    @pytest.mark.asyncio
    async def test_record_fill_creates_execution_record(self, tracker, mock_session_factory):
        """record_fill creates an ExecutionRecord in the DB."""
        _, session = mock_session_factory
        # Mock the query to return an Order
        mock_order = MagicMock()
        mock_order.expected_price = None
        mock_order.ib_perm_id = 100
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_order
        session.execute = AsyncMock(return_value=mock_result)

        trade = make_mock_trade()
        fill = self._make_fill()

        await tracker.record_fill("order-001", trade, fill)

        # Verify session.add was called (the ExecutionRecord was added)
        session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_fill_with_slippage(self, tracker, mock_session_factory):
        """Slippage is calculated when expected_price is set on the Order."""
        _, session = mock_session_factory
        mock_order = MagicMock()
        mock_order.expected_price = 5.00
        mock_order.action = "BUY"
        mock_order.ib_perm_id = 100
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_order
        session.execute = AsyncMock(return_value=mock_result)

        trade = make_mock_trade()
        fill = self._make_fill(price=5.10)

        await tracker.record_fill("order-001", trade, fill)

        # Verify the ExecutionRecord that was added has slippage data
        added_record = session.add.call_args[0][0]
        assert added_record.slippage is not None
        assert added_record.slippage_bps is not None

    @pytest.mark.asyncio
    async def test_duplicate_exec_id_handled(self, tracker, mock_session_factory):
        """Duplicate exec_id (IntegrityError) is handled gracefully."""
        from sqlalchemy.exc import IntegrityError

        _, session = mock_session_factory
        mock_order = MagicMock()
        mock_order.expected_price = None
        mock_order.ib_perm_id = 100
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_order
        session.execute = AsyncMock(return_value=mock_result)
        session.commit = AsyncMock(
            side_effect=IntegrityError("dup", {}, Exception("unique"))
        )

        trade = make_mock_trade()
        fill = self._make_fill()

        # Should NOT raise -- IntegrityError is caught
        await tracker.record_fill("order-001", trade, fill)


# ============================================================================
# OrderRecoveryManager Tests
# ============================================================================


class TestOrderRecoveryManager:
    """Tests for post-reconnect order reconciliation."""

    @pytest.fixture
    def mock_ib(self):
        """Mock IB connection for recovery.

        Uses MagicMock (not AsyncMock) because ib.trades() is synchronous.
        Only reqOpenOrdersAsync is async.
        """
        ib = MagicMock()
        ib.reqOpenOrdersAsync = AsyncMock(return_value=[])
        ib.trades = MagicMock(return_value=[])
        return ib

    @pytest.fixture
    def mock_order_tracker(self):
        """Mock OrderTracker for recovery."""
        tracker = MagicMock(spec=OrderTracker)
        tracker.create_order = MagicMock(return_value=MagicMock(spec=OrderStateMachine))
        tracker.get_machine = MagicMock(return_value=None)
        tracker.handle_ib_status = AsyncMock()
        return tracker

    @pytest.fixture
    def mock_execution_service(self):
        """Mock OrderExecutionService for resubscription."""
        svc = MagicMock(spec=OrderExecutionService)
        svc.resubscribe_trade = MagicMock()
        return svc

    @pytest.fixture
    def mock_session_factory(self):
        """Mock session factory for recovery."""
        factory = MagicMock()
        session = AsyncMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.close = AsyncMock()
        factory.return_value = session
        return factory, session

    @pytest.fixture
    def recovery(self, mock_ib, mock_order_tracker, mock_execution_service, mock_session_factory):
        """Create OrderRecoveryManager with mocks."""
        factory, _ = mock_session_factory
        return OrderRecoveryManager(
            ib=mock_ib,
            order_tracker=mock_order_tracker,
            execution_service=mock_execution_service,
            session_factory=factory,
        )

    @pytest.mark.asyncio
    async def test_recover_open_order(self, recovery, mock_ib, mock_order_tracker, mock_execution_service, mock_session_factory):
        """In-flight order found in IB open orders is recovered and resubscribed."""
        _, session = mock_session_factory

        # IB returns one open order
        ib_trade = make_mock_trade(perm_id=999, status="Submitted")
        mock_ib.reqOpenOrdersAsync = AsyncMock(return_value=[ib_trade])

        # DB has one in-flight order matching by perm_id
        db_order = MagicMock()
        db_order.id = "order-abc"
        db_order.ib_perm_id = 999
        db_order.current_state = "SUBMITTED"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [db_order]
        session.execute = AsyncMock(return_value=mock_result)

        summary = await recovery.recover_after_reconnect()

        assert summary["recovered"] == 1
        mock_execution_service.resubscribe_trade.assert_called_once_with(
            "order-abc", ib_trade
        )

    @pytest.mark.asyncio
    async def test_recover_filled_order(self, recovery, mock_ib, mock_session_factory):
        """In-flight order NOT in IB open orders but found in completed trades as Filled."""
        _, session = mock_session_factory

        # IB returns no open orders -- but has a completed Filled trade
        completed_trade = make_mock_trade(perm_id=888, status="Filled")
        mock_ib.trades.return_value = [completed_trade]

        # DB has one in-flight order with this perm_id
        db_order = MagicMock()
        db_order.id = "order-def"
        db_order.ib_perm_id = 888
        db_order.current_state = "SUBMITTED"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [db_order]
        session.execute = AsyncMock(return_value=mock_result)

        summary = await recovery.recover_after_reconnect()

        assert summary["filled"] == 1

    @pytest.mark.asyncio
    async def test_recover_missing_order(self, recovery, mock_ib, mock_session_factory):
        """In-flight order NOT in IB anywhere is marked as orphaned."""
        _, session = mock_session_factory

        # IB returns nothing -- no open orders, no completed trades

        # DB has an in-flight order with perm_id that IB doesn't know about
        db_order = MagicMock()
        db_order.id = "order-ghi"
        db_order.ib_perm_id = 777
        db_order.current_state = "SUBMITTED"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [db_order]
        session.execute = AsyncMock(return_value=mock_result)

        summary = await recovery.recover_after_reconnect()

        # No matching trades at all -- cancelled returns None from _check_completed_trade
        assert summary["orphaned"] == 1
