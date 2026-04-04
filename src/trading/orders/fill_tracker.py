"""Event-driven fill recording with slippage measurement.

FillTracker turns IB's fill and commission events into persistent
ExecutionRecords with slippage analysis. This is the audit trail for
every execution -- every fill creates a DB record, every commission
report updates that record and accumulates on the parent Order.

Handles the commission-before-fill race condition via a pending
commissions buffer: if a CommissionReport arrives before the fill
for the same execId, it is buffered and applied once the fill lands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from ib_async import CommissionReport, Fill, Trade
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from trading.db.models import ExecutionRecord as ExecutionRecordORM, Order
from trading.db.session import get_session
from trading.orders.models import SlippageReport, calculate_slippage

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

logger = structlog.get_logger(component="fill_tracker")


class FillTracker:
    """Tracks IB fill events and persists ExecutionRecords to the database.

    Each fill creates an ExecutionRecord with price, quantity, timestamps,
    and slippage (when expected_price is available on the parent Order).
    Commission reports update the execution record and accumulate on the
    parent Order's total_commission.

    Args:
        session_factory: async_sessionmaker for DB access.
    """

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory
        self._pending_commissions: dict[str, CommissionReport] = {}

    async def on_fill(
        self, order_id: str, trade: Trade, fill: Fill
    ) -> None:
        """Event handler entry point for fill events.

        Called by OrderExecutionService._on_fill when IB fires a
        fillEvent on a Trade object. Delegates to record_fill for
        DB persistence.

        Args:
            order_id: Internal order ID.
            trade: The ib_async Trade object.
            fill: The Fill object from IB.
        """
        await self.record_fill(order_id, trade, fill)

    async def on_commission(
        self,
        order_id: str,
        trade: Trade,
        fill: Fill,
        report: CommissionReport,
    ) -> None:
        """Event handler entry point for commission report events.

        Called by OrderExecutionService._on_commission when IB fires
        a commissionReportEvent on a Trade object.

        Args:
            order_id: Internal order ID.
            trade: The ib_async Trade object.
            fill: The Fill associated with this commission.
            report: The CommissionReport from IB.
        """
        await self.record_commission(order_id, trade, fill, report)

    async def record_fill(
        self, order_id: str, trade: Trade, fill: Fill
    ) -> None:
        """Record a fill execution to the database.

        Creates an ExecutionRecord in the DB with fill details from
        IB's Execution object. Calculates slippage if the parent Order
        has an expected_price set. Updates the Order's fill_price and
        filled_quantity with the cumulative average.

        Handles duplicate exec_id gracefully via IntegrityError catch
        (IB may fire the same fill event more than once).

        After recording the fill, checks the pending commissions buffer
        for any commission report that arrived before this fill.

        Args:
            order_id: Internal order ID.
            trade: The ib_async Trade object.
            fill: The Fill object from IB containing execution details.
        """
        execution = fill.execution
        exec_id = execution.execId

        try:
            async with get_session(self._session_factory) as session:
                # Look up the parent Order for expected_price and action
                result = await session.execute(
                    select(Order).where(Order.id == order_id)
                )
                db_order = result.scalar_one_or_none()

                # Calculate slippage if expected_price is available
                slippage_dollars: float | None = None
                slippage_bps: float | None = None
                expected_price: float | None = None

                if db_order is not None and db_order.expected_price is not None:
                    expected_price = db_order.expected_price
                    action = db_order.action
                    slippage_dollars, slippage_bps = calculate_slippage(
                        action=action,
                        expected_price=expected_price,
                        fill_price=execution.price,
                        quantity=execution.shares,
                    )

                # Create ExecutionRecord in DB
                exec_record = ExecutionRecordORM(
                    order_id=order_id,
                    exec_id=exec_id,
                    side=execution.side,
                    quantity=execution.shares,
                    price=execution.price,
                    avg_price=execution.avgPrice,
                    cum_qty=execution.cumQty,
                    exchange=execution.exchange,
                    liquidity=getattr(execution, "lastLiquidity", None),
                    expected_price=expected_price,
                    slippage=slippage_dollars,
                    slippage_bps=slippage_bps,
                )
                session.add(exec_record)

                # Update Order record with cumulative fill data
                if db_order is not None:
                    db_order.fill_price = execution.avgPrice
                    db_order.filled_quantity = execution.cumQty
                    # Set ib_perm_id if not yet assigned
                    if db_order.ib_perm_id is None and execution.permId:
                        db_order.ib_perm_id = execution.permId

            logger.info(
                "fill_recorded",
                trigger="fill_recorded",
                order_id=order_id,
                exec_id=exec_id,
                side=execution.side,
                quantity=execution.shares,
                price=execution.price,
                avg_price=execution.avgPrice,
                cum_qty=execution.cumQty,
                slippage=slippage_dollars,
                slippage_bps=slippage_bps,
            )

            # Check for pending commission that arrived before this fill
            pending = self._pending_commissions.pop(exec_id, None)
            if pending is not None:
                logger.debug(
                    "applying_buffered_commission",
                    trigger="applying_buffered_commission",
                    order_id=order_id,
                    exec_id=exec_id,
                )
                await self._apply_commission(order_id, exec_id, pending)

        except IntegrityError:
            # Duplicate exec_id -- IB fired the same fill event twice
            logger.warning(
                "duplicate_fill_ignored",
                trigger="duplicate_fill_ignored",
                order_id=order_id,
                exec_id=exec_id,
            )
        except Exception:
            logger.error(
                "fill_record_failed",
                trigger="fill_record_failed",
                order_id=order_id,
                exec_id=exec_id,
                exc_info=True,
            )

    async def record_commission(
        self,
        order_id: str,
        trade: Trade,
        fill: Fill,
        report: CommissionReport,
    ) -> None:
        """Record a commission report for a fill execution.

        Finds the ExecutionRecord by exec_id and updates its commission
        and realized_pnl fields. Also accumulates the commission on the
        parent Order's total_commission.

        If the commission arrives before the fill (race condition), the
        report is buffered in _pending_commissions and applied later
        when record_fill processes the fill.

        Args:
            order_id: Internal order ID.
            trade: The ib_async Trade object.
            fill: The Fill associated with this commission.
            report: The CommissionReport from IB.
        """
        exec_id = fill.execution.execId

        try:
            async with get_session(self._session_factory) as session:
                # Find the ExecutionRecord for this exec_id
                result = await session.execute(
                    select(ExecutionRecordORM).where(
                        ExecutionRecordORM.exec_id == exec_id
                    )
                )
                exec_record = result.scalar_one_or_none()

                if exec_record is None:
                    # Commission arrived before fill -- buffer it
                    self._pending_commissions[exec_id] = report
                    logger.debug(
                        "commission_buffered",
                        trigger="commission_buffered",
                        order_id=order_id,
                        exec_id=exec_id,
                        commission=report.commission,
                    )
                    return

                # Update execution record with commission data
                exec_record.commission = report.commission
                if report.realizedPNL != float("inf"):
                    exec_record.realized_pnl = report.realizedPNL

                # Accumulate commission on parent Order
                order_result = await session.execute(
                    select(Order).where(Order.id == order_id)
                )
                db_order = order_result.scalar_one_or_none()
                if db_order is not None:
                    current = db_order.total_commission or 0.0
                    db_order.total_commission = current + report.commission

            logger.info(
                "commission_recorded",
                trigger="commission_recorded",
                order_id=order_id,
                exec_id=exec_id,
                commission=report.commission,
                realized_pnl=(
                    report.realizedPNL
                    if report.realizedPNL != float("inf")
                    else None
                ),
            )

        except Exception:
            logger.error(
                "commission_record_failed",
                trigger="commission_record_failed",
                order_id=order_id,
                exec_id=exec_id,
                exc_info=True,
            )

    async def get_slippage_report(
        self, order_id: str
    ) -> SlippageReport | None:
        """Generate a slippage report for a completed order.

        Aggregates all fills for the order and calculates total
        slippage relative to the expected price. Returns None if
        the order has no expected_price or no fills.

        Args:
            order_id: Internal order ID.

        Returns:
            SlippageReport if slippage can be calculated, None otherwise.
        """
        try:
            async with get_session(self._session_factory) as session:
                # Get the parent Order for expected_price and action
                order_result = await session.execute(
                    select(Order).where(Order.id == order_id)
                )
                db_order = order_result.scalar_one_or_none()

                if db_order is None or db_order.expected_price is None:
                    return None

                # Get all fills for this order
                fills_result = await session.execute(
                    select(ExecutionRecordORM).where(
                        ExecutionRecordORM.order_id == order_id
                    )
                )
                fills = list(fills_result.scalars().all())

                if not fills:
                    return None

                # Use the last fill's avg_price as the aggregate fill price
                # (IB's avgPrice is cumulative across all fills for an order)
                last_fill = max(fills, key=lambda f: f.cum_qty)
                avg_fill_price = last_fill.avg_price
                total_quantity = last_fill.cum_qty

                slippage_dollars, slippage_bps = calculate_slippage(
                    action=db_order.action,
                    expected_price=db_order.expected_price,
                    fill_price=avg_fill_price,
                    quantity=total_quantity,
                )

                return SlippageReport(
                    order_id=order_id,
                    action=db_order.action,
                    expected_price=db_order.expected_price,
                    avg_fill_price=avg_fill_price,
                    quantity=total_quantity,
                    slippage_dollars=slippage_dollars,
                    slippage_bps=slippage_bps,
                )

        except Exception:
            logger.error(
                "slippage_report_failed",
                trigger="slippage_report_failed",
                order_id=order_id,
                exc_info=True,
            )
            return None

    async def _apply_commission(
        self,
        order_id: str,
        exec_id: str,
        report: CommissionReport,
    ) -> None:
        """Apply a buffered commission report to an existing ExecutionRecord.

        Called when a commission was buffered (arrived before the fill)
        and the fill has now been recorded.

        Args:
            order_id: Internal order ID.
            exec_id: The IB execution ID.
            report: The buffered CommissionReport.
        """
        try:
            async with get_session(self._session_factory) as session:
                result = await session.execute(
                    select(ExecutionRecordORM).where(
                        ExecutionRecordORM.exec_id == exec_id
                    )
                )
                exec_record = result.scalar_one_or_none()

                if exec_record is not None:
                    exec_record.commission = report.commission
                    if report.realizedPNL != float("inf"):
                        exec_record.realized_pnl = report.realizedPNL

                # Accumulate commission on parent Order
                order_result = await session.execute(
                    select(Order).where(Order.id == order_id)
                )
                db_order = order_result.scalar_one_or_none()
                if db_order is not None:
                    current = db_order.total_commission or 0.0
                    db_order.total_commission = current + report.commission

            logger.info(
                "buffered_commission_applied",
                trigger="buffered_commission_applied",
                order_id=order_id,
                exec_id=exec_id,
                commission=report.commission,
            )

        except Exception:
            logger.error(
                "buffered_commission_apply_failed",
                trigger="buffered_commission_apply_failed",
                order_id=order_id,
                exec_id=exec_id,
                exc_info=True,
            )
