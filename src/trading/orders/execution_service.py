"""Risk-gated order execution service.

The single entry point for all order placement. Every order must pass
through submit_order(), which enforces the risk gate via
evaluate_with_failsafe() before any call to ib.placeOrder().

Bridges TradeProposal (Phase 3 domain) to IB's placeOrder API:
1. Risk-validate via evaluate_with_failsafe
2. Construct IB contract/order from TradeProposal legs
3. Create DB Order record with proposal_id linkage
4. Place order via ib.placeOrder(contract, order)
5. Subscribe to Trade events for status tracking
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog
from ib_async import IB, MarketOrder, Trade

from trading.db.models import Order
from trading.db.session import get_session
from trading.orders.combo_builder import ComboOrderBuilder
from trading.orders.tracker import OrderTracker
from trading.risk.manager import RiskManager, evaluate_with_failsafe
from trading.risk.models import RiskDecision, TradeProposal

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

logger = structlog.get_logger(component="execution_service")


class OrderExecutionService:
    """Risk-gated order submission pipeline.

    Every order reaches IB only after passing through
    evaluate_with_failsafe(). Single-leg orders use the leg's
    contract and order directly. Multi-leg orders use
    ComboOrderBuilder to construct a BAG contract with
    NonGuaranteed routing.

    Args:
        ib: IB connection instance from ib_async.
        risk_manager: RiskManager for trade evaluation.
        order_tracker: OrderTracker for state machine management.
        session_factory: async_sessionmaker for DB access.
    """

    def __init__(
        self,
        ib: IB,
        risk_manager: RiskManager,
        order_tracker: OrderTracker,
        session_factory: async_sessionmaker,
    ) -> None:
        self._ib = ib
        self._risk_manager = risk_manager
        self._order_tracker = order_tracker
        self._session_factory = session_factory
        self._fill_tracker: Any | None = None
        self._active_trades: dict[str, Trade] = {}

    @property
    def fill_tracker(self) -> Any | None:
        """Get the fill tracker (set after construction by Plan 03)."""
        return self._fill_tracker

    @fill_tracker.setter
    def fill_tracker(self, value: Any) -> None:
        """Set the fill tracker (called by Plan 03 after construction)."""
        self._fill_tracker = value

    async def submit_order(
        self,
        proposal: TradeProposal,
        timeout: float = 10.0,
    ) -> tuple[RiskDecision, Trade | None]:
        """Submit an order through the risk gate.

        Flow:
        1. evaluate_with_failsafe -- ALWAYS FIRST, no bypass
        2. Rejected? Return (decision, None)
        3. Determine single-leg or multi-leg
        4. Create DB Order record
        5. Create state machine via OrderTracker
        6. Place order via ib.placeOrder
        7. Subscribe to Trade events
        8. Return (decision, trade)

        Args:
            proposal: Trade proposal from the risk engine domain.
            timeout: Timeout for the risk evaluation (default 10s).

        Returns:
            Tuple of (RiskDecision, Trade | None). Trade is None
            if the risk check rejected the proposal.
        """
        # 1. Risk gate -- ALWAYS first, no bypass
        decision = await evaluate_with_failsafe(
            self._risk_manager, proposal, timeout=timeout
        )

        if not decision.approved:
            logger.warning(
                "order_rejected_by_risk",
                proposal_id=proposal.proposal_id,
                violated_rule=(
                    decision.violated_rule.value
                    if decision.violated_rule
                    else None
                ),
                details=decision.details,
            )
            return decision, None

        # 2. Determine single-leg vs multi-leg
        is_multi_leg = len(proposal.legs) > 1

        if is_multi_leg:
            contract, order = self._build_multi_leg(proposal)
        else:
            contract, order = self._build_single_leg(proposal)

        # 3. Create DB Order record
        order_id = await self._create_db_order(proposal, contract, order, is_multi_leg)

        # 4. Create state machine via OrderTracker
        self._order_tracker.create_order(order_id)

        # 5. Place order via ib.placeOrder
        trade = self._ib.placeOrder(contract, order)

        # Store for cancel/recovery lookup
        self._active_trades[order_id] = trade

        logger.info(
            "order_placed",
            order_id=order_id,
            proposal_id=proposal.proposal_id,
            symbol=proposal.legs[0].symbol,
            is_multi_leg=is_multi_leg,
            num_legs=len(proposal.legs),
            ib_order_id=trade.order.orderId,
        )

        # 6. Subscribe to Trade events
        self._subscribe_trade_events(order_id, trade)

        return decision, trade

    async def cancel_order(self, order_id: str) -> Trade | None:
        """Cancel an active order.

        Transitions the state machine to PENDING_CANCEL and sends
        the cancel request to IB. Trade events will fire the
        Cancelled/ApiCancelled status which handle_ib_status processes.

        Args:
            order_id: The internal order ID to cancel.

        Returns:
            The Trade object if found and cancel sent, None otherwise.
        """
        trade = self._active_trades.get(order_id)
        if trade is None:
            logger.warning(
                "cancel_order_not_found",
                order_id=order_id,
            )
            return None

        # Transition state machine to PENDING_CANCEL
        try:
            await self._order_tracker.transition(order_id, "request_cancel")
        except Exception:
            logger.warning(
                "cancel_transition_failed",
                order_id=order_id,
                exc_info=True,
            )
            # Still attempt the IB cancel even if state transition fails

        # Send cancel to IB
        self._ib.cancelOrder(trade.order)

        logger.info(
            "cancel_order_sent",
            order_id=order_id,
            ib_order_id=trade.order.orderId,
        )

        return trade

    def _build_single_leg(
        self, proposal: TradeProposal
    ) -> tuple[Any, Any]:
        """Build contract and order for a single-leg trade.

        Uses the leg's pre-qualified contract and constructs the
        appropriate order type (Market, Limit, or Stop).

        Args:
            proposal: Trade proposal with exactly one leg.

        Returns:
            Tuple of (contract, order) for ib.placeOrder.
        """
        leg = proposal.legs[0]
        contract = leg.contract

        order = self._build_order_from_leg(leg)

        logger.debug(
            "built_single_leg_order",
            symbol=leg.symbol,
            action=leg.action,
            quantity=leg.quantity,
            order_type=type(order).__name__,
        )

        return contract, order

    def _build_multi_leg(
        self, proposal: TradeProposal
    ) -> tuple[Any, Any]:
        """Build combo contract and order for a multi-leg trade.

        Uses ComboOrderBuilder to construct a BAG contract with
        NonGuaranteed routing for SMART-routed combos.

        Args:
            proposal: Trade proposal with multiple legs.

        Returns:
            Tuple of (bag_contract, order) for ib.placeOrder.
        """
        symbol = proposal.legs[0].symbol

        # Build BAG contract from TradeLeg objects
        bag = ComboOrderBuilder.build_from_trade_legs(
            symbol=symbol,
            trade_legs=proposal.legs,
        )

        # Use the first leg's order to determine order type,
        # or default to LimitOrder for combos
        first_leg = proposal.legs[0]
        order = self._build_order_from_leg(first_leg)

        # Apply NonGuaranteed routing for SMART combos
        ComboOrderBuilder.apply_combo_routing(order)

        logger.debug(
            "built_multi_leg_order",
            symbol=symbol,
            num_legs=len(proposal.legs),
            order_type=type(order).__name__,
        )

        return bag, order

    @staticmethod
    def _build_order_from_leg(leg: Any) -> Any:
        """Construct an IB order from a TradeLeg's order or defaults.

        If the leg has a pre-built ib_async Order object, returns it
        directly. Otherwise, creates a MarketOrder as the default.

        Args:
            leg: TradeLeg with action, quantity, and optional order.

        Returns:
            An ib_async Order object (MarketOrder, LimitOrder, etc.).
        """
        if leg.order is not None:
            return leg.order

        # Default to MarketOrder when no order is pre-built
        return MarketOrder(leg.action, leg.quantity)

    async def _create_db_order(
        self,
        proposal: TradeProposal,
        contract: Any,
        order: Any,
        is_multi_leg: bool,
    ) -> str:
        """Create a DB Order record before placing with IB.

        Links the order to the proposal_id for audit trail back
        to the risk decision.

        Args:
            proposal: The trade proposal being executed.
            contract: The IB contract (single or BAG).
            order: The IB order object.
            is_multi_leg: Whether this is a combo order.

        Returns:
            The generated order ID (UUID string).
        """
        first_leg = proposal.legs[0]

        # Determine order type name and prices
        order_type = type(order).__name__
        limit_price = getattr(order, "lmtPrice", None)
        stop_price = getattr(order, "auxPrice", None)

        # Build combo_legs JSON for multi-leg audit
        combo_legs_json: str | None = None
        if is_multi_leg:
            combo_legs_json = json.dumps(
                [
                    {
                        "symbol": leg.symbol,
                        "action": leg.action,
                        "quantity": leg.quantity,
                        "right": leg.right,
                        "strike": leg.strike,
                        "expiry": leg.expiry,
                    }
                    for leg in proposal.legs
                ]
            )

        db_order = Order(
            symbol=first_leg.symbol,
            sec_type=first_leg.sec_type,
            action=first_leg.action,
            quantity=first_leg.quantity,
            order_type=order_type,
            limit_price=limit_price,
            stop_price=stop_price,
            proposal_id=proposal.proposal_id,
            combo_legs=combo_legs_json,
        )

        async with get_session(self._session_factory) as session:
            session.add(db_order)
            await session.flush()
            order_id = db_order.id

        logger.debug(
            "db_order_created",
            order_id=order_id,
            proposal_id=proposal.proposal_id,
            symbol=first_leg.symbol,
        )

        return order_id

    def _subscribe_trade_events(self, order_id: str, trade: Trade) -> None:
        """Subscribe to a Trade's lifecycle events.

        Bridges IB Trade events to OrderTracker.handle_ib_status
        for state machine transitions and DB persistence.

        Args:
            order_id: Internal order ID for state tracking.
            trade: The ib_async Trade object from placeOrder.
        """

        async def _on_status(t: Trade) -> None:
            """Handle order status changes from IB."""
            status = t.orderStatus.status
            await self._order_tracker.handle_ib_status(order_id, status)

            # Update IB IDs on first status event
            if t.order.permId:
                await self._update_ib_ids(
                    order_id, t.order.orderId, t.order.permId
                )

            # Remove from active trades when done
            if t.isDone():
                self._active_trades.pop(order_id, None)

        async def _on_fill(t: Trade, fill: Any) -> None:
            """Handle fill events -- delegate to fill_tracker if set."""
            if self._fill_tracker is not None:
                await self._fill_tracker.on_fill(order_id, t, fill)

        async def _on_commission(
            t: Trade, fill: Any, report: Any
        ) -> None:
            """Handle commission reports -- delegate to fill_tracker if set."""
            if self._fill_tracker is not None:
                await self._fill_tracker.on_commission(
                    order_id, t, fill, report
                )

        trade.statusEvent += _on_status
        trade.fillEvent += _on_fill
        trade.commissionReportEvent += _on_commission

    async def _update_ib_ids(
        self, order_id: str, ib_order_id: int, ib_perm_id: int
    ) -> None:
        """Update the DB Order with IB-assigned identifiers.

        Called on the first status event after placeOrder, when IB
        assigns the permanent order ID.

        Args:
            order_id: Internal order ID.
            ib_order_id: Session-local IB order ID.
            ib_perm_id: Permanent IB order ID (stable across sessions).
        """
        try:
            async with get_session(self._session_factory) as session:
                from sqlalchemy import select

                result = await session.execute(
                    select(Order).where(Order.id == order_id)
                )
                db_order = result.scalar_one_or_none()
                if db_order is not None:
                    db_order.ib_order_id = ib_order_id
                    db_order.ib_perm_id = ib_perm_id
        except Exception:
            logger.warning(
                "failed_to_update_ib_ids",
                order_id=order_id,
                exc_info=True,
            )

    def resubscribe_trade(self, order_id: str, trade: Trade) -> None:
        """Resubscribe to Trade events after reconnection recovery.

        Called by OrderRecoveryManager when an in-flight order is found
        in IB's open orders after reconnect. Re-registers the Trade in
        the active trades dict and subscribes to its lifecycle events.

        Args:
            order_id: Internal order ID.
            trade: The IB Trade object from reqOpenOrdersAsync.
        """
        self._active_trades[order_id] = trade
        self._subscribe_trade_events(order_id, trade)

        logger.info(
            "trade_resubscribed",
            order_id=order_id,
            ib_order_id=trade.order.orderId,
            ib_perm_id=trade.order.permId,
            status=trade.orderStatus.status,
        )
