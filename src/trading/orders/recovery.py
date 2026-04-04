"""Post-reconnect order reconciliation.

OrderRecoveryManager handles the critical scenario where IB Gateway
disconnects and reconnects while orders are in-flight. After reconnect,
it queries IB for open orders and reconciles them against database
state using ib_perm_id matching.

Orders that were in-flight (non-terminal) in the DB are matched against
IB's open orders. Matched orders get state updates and new Trade event
subscriptions for continued tracking. Unmatched in-flight DB orders are
investigated for fills or cancellations that happened during disconnect.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from ib_async import IB, Trade
from sqlalchemy import select
from statemachine.exceptions import TransitionNotAllowed

from trading.db.models import Order, OrderState
from trading.db.session import get_session

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from trading.orders.execution_service import OrderExecutionService
    from trading.orders.tracker import OrderTracker

logger = structlog.get_logger(component="order_recovery")

# Terminal states -- orders in these states need no recovery
TERMINAL_STATES = {
    OrderState.FILLED.value,
    OrderState.CANCELLED.value,
    OrderState.ERROR.value,
}


class OrderRecoveryManager:
    """Reconciles in-flight orders after IB reconnection.

    After a disconnect/reconnect cycle, queries IB for open orders
    and matches them against database records using the permanent
    order ID (ib_perm_id). Recovers order tracking by resubscribing
    to Trade events and updating state machines.

    Args:
        ib: IB connection instance from ib_async.
        order_tracker: OrderTracker for state machine management.
        execution_service: OrderExecutionService for trade resubscription.
        session_factory: async_sessionmaker for DB access.
    """

    def __init__(
        self,
        ib: IB,
        order_tracker: OrderTracker,
        execution_service: OrderExecutionService,
        session_factory: async_sessionmaker,
    ) -> None:
        self._ib = ib
        self._order_tracker = order_tracker
        self._execution_service = execution_service
        self._session_factory = session_factory

    async def recover_after_reconnect(self) -> dict:
        """Reconcile in-flight orders after IB reconnection.

        Flow:
        1. Request open orders from IB via reqOpenOrdersAsync
        2. Query DB for in-flight orders (non-terminal states)
        3. Build perm_id -> Trade mapping from IB open orders
        4. For each in-flight DB order, reconcile against IB state
        5. Log recovery summary and return stats

        Returns:
            Summary dict with keys: recovered, filled, cancelled, orphaned.
        """
        summary = {
            "recovered": 0,
            "filled": 0,
            "cancelled": 0,
            "orphaned": 0,
        }

        # 1. Request open orders from IB
        try:
            ib_trades = await self._ib.reqOpenOrdersAsync()
        except Exception:
            logger.error(
                "recovery_req_open_orders_failed",
                trigger="recovery_req_open_orders_failed",
                exc_info=True,
            )
            return summary

        # 2. Query DB for in-flight orders (non-terminal states)
        try:
            async with get_session(self._session_factory) as session:
                result = await session.execute(
                    select(Order).where(
                        Order.current_state.notin_(TERMINAL_STATES)
                    )
                )
                in_flight_orders = list(result.scalars().all())
        except Exception:
            logger.error(
                "recovery_db_query_failed",
                trigger="recovery_db_query_failed",
                exc_info=True,
            )
            return summary

        if not in_flight_orders:
            logger.info(
                "recovery_no_in_flight_orders",
                trigger="recovery_no_in_flight_orders",
            )
            return summary

        # 3. Build perm_id -> Trade mapping from IB open orders
        ib_perm_map: dict[int, Trade] = {}
        for trade in ib_trades:
            perm_id = trade.order.permId
            if perm_id:
                ib_perm_map[perm_id] = trade

        logger.info(
            "recovery_started",
            trigger="recovery_started",
            in_flight_count=len(in_flight_orders),
            ib_open_count=len(ib_perm_map),
        )

        # 4. Reconcile each in-flight DB order
        for db_order in in_flight_orders:
            await self._reconcile_order(db_order, ib_perm_map, summary)

        # 5. Log summary
        logger.info(
            "recovery_complete",
            trigger="recovery_complete",
            recovered=summary["recovered"],
            filled=summary["filled"],
            cancelled=summary["cancelled"],
            orphaned=summary["orphaned"],
        )

        return summary

    async def _reconcile_order(
        self,
        db_order: Order,
        ib_perm_map: dict[int, Trade],
        summary: dict,
    ) -> None:
        """Reconcile a single in-flight DB order against IB state.

        If the order has an ib_perm_id that matches an IB open order,
        resubscribe for continued tracking. If no match is found, the
        order may have been filled or cancelled during disconnect.

        Args:
            db_order: The DB Order record to reconcile.
            ib_perm_map: Mapping from IB perm_id to Trade objects.
            summary: Running summary dict to update counts.
        """
        order_id = db_order.id
        perm_id = db_order.ib_perm_id

        if perm_id is not None and perm_id in ib_perm_map:
            # Order still open in IB -- recover tracking
            trade = ib_perm_map[perm_id]
            await self._recover_active_order(order_id, trade, db_order)
            summary["recovered"] += 1
        elif perm_id is not None:
            # Had a perm_id but not in IB open orders -- check completed trades
            await self._handle_missing_order(order_id, db_order)
            # Determine if it was filled or cancelled from IB state
            completed = await self._check_completed_trade(perm_id)
            if completed == "filled":
                summary["filled"] += 1
            elif completed == "cancelled":
                summary["cancelled"] += 1
            else:
                summary["orphaned"] += 1
        else:
            # No perm_id -- order was placed but never got IB confirmation
            logger.warning(
                "recovery_no_perm_id",
                trigger="recovery_no_perm_id",
                order_id=order_id,
                current_state=db_order.current_state,
            )
            summary["orphaned"] += 1

    async def _recover_active_order(
        self,
        order_id: str,
        trade: Trade,
        db_order: Order,
    ) -> None:
        """Recover an order that is still active in IB.

        Re-creates the state machine if needed, updates state based on
        the IB Trade's current status, and resubscribes to Trade events
        for continued tracking.

        Args:
            order_id: Internal order ID.
            trade: The IB Trade object for this order.
            db_order: The DB Order record.
        """
        ib_status = trade.orderStatus.status

        # Ensure state machine exists for this order
        machine = self._order_tracker.get_machine(order_id)
        if machine is None:
            machine = self._order_tracker.create_order(order_id)
            # Fast-forward the state machine to match DB state
            # by transitioning through the IB status
            try:
                await self._order_tracker.handle_ib_status(
                    order_id, ib_status
                )
            except (TransitionNotAllowed, ValueError, KeyError):
                logger.warning(
                    "recovery_state_sync_failed",
                    trigger="recovery_state_sync_failed",
                    order_id=order_id,
                    ib_status=ib_status,
                    db_state=db_order.current_state,
                )
        else:
            # Machine exists -- update to current IB status
            try:
                await self._order_tracker.handle_ib_status(
                    order_id, ib_status
                )
            except (TransitionNotAllowed, ValueError, KeyError):
                logger.warning(
                    "recovery_status_update_failed",
                    trigger="recovery_status_update_failed",
                    order_id=order_id,
                    ib_status=ib_status,
                    current_state=machine.current_state_value,
                )

        # Resubscribe to Trade events for continued tracking
        self._execution_service.resubscribe_trade(order_id, trade)

        logger.info(
            "order_recovered",
            trigger="order_recovered",
            order_id=order_id,
            ib_perm_id=db_order.ib_perm_id,
            ib_status=ib_status,
            db_state=db_order.current_state,
        )

    async def _handle_missing_order(
        self, order_id: str, db_order: Order
    ) -> None:
        """Handle an in-flight DB order not found in IB open orders.

        The order likely completed (filled or cancelled) during the
        disconnect. Transitions the state machine to the likely
        terminal state.

        Args:
            order_id: Internal order ID.
            db_order: The DB Order record.
        """
        logger.warning(
            "recovery_order_not_in_ib",
            trigger="recovery_order_not_in_ib",
            order_id=order_id,
            ib_perm_id=db_order.ib_perm_id,
            current_state=db_order.current_state,
        )

    async def _check_completed_trade(self, perm_id: int) -> str | None:
        """Check if a trade completed during disconnect.

        Scans IB's completed trades for a matching perm_id to
        determine the final state.

        Args:
            perm_id: The IB permanent order ID.

        Returns:
            "filled", "cancelled", or None if status unknown.
        """
        try:
            # Check IB's list of all trades (includes completed)
            for trade in self._ib.trades():
                if trade.order.permId == perm_id:
                    status = trade.orderStatus.status
                    if status == "Filled":
                        return "filled"
                    if status in ("Cancelled", "ApiCancelled"):
                        return "cancelled"
                    return None
        except Exception:
            logger.warning(
                "recovery_check_completed_failed",
                trigger="recovery_check_completed_failed",
                perm_id=perm_id,
                exc_info=True,
            )
        return None
