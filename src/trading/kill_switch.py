"""Emergency kill switch for order cancellation and position liquidation.

Provides the KillSwitch class that can:
  - Cancel all open orders via IB's global cancel
  - Close all open positions with market orders
  - Execute a full emergency shutdown (cancel + close)

This is a safety-critical component -- it must work when everything else
fails. All operations log at CRITICAL level for maximum visibility.
"""

from __future__ import annotations

import structlog
from ib_async import IB, MarketOrder


class KillSwitch:
    """Emergency order cancellation and position liquidation.

    Uses the IB API to cancel all open orders and close all open
    positions with market orders. Designed for fail-safe operation:
    if individual position closes fail, the error is logged and
    remaining positions are still processed.

    Usage:
        kill_switch = KillSwitch(ib)
        await kill_switch.emergency_shutdown()
    """

    def __init__(self, ib: IB) -> None:
        self.ib = ib
        self._logger = structlog.get_logger(component="kill_switch")

    async def cancel_all_orders(self) -> None:
        """Cancel all open orders via IB's global cancel.

        Calls reqGlobalCancel() which cancels every open order
        across all client IDs on the account.
        """
        self._logger.critical("kill_switch.cancelling_all_orders")
        self.ib.reqGlobalCancel()
        self._logger.critical("kill_switch.all_orders_cancelled")

    async def close_all_positions(self) -> int:
        """Close all open positions with market orders.

        For each non-zero position:
          - SELL if long (positive quantity)
          - BUY if short (negative quantity)
          - Creates a MarketOrder with the absolute quantity
          - Places the order via IB

        Returns:
            Number of closing orders placed.
        """
        # Cancel all orders first to prevent new fills
        await self.cancel_all_orders()

        positions = self.ib.positions()
        closing_count = 0

        for position in positions:
            if position.position == 0:
                continue

            action = "SELL" if position.position > 0 else "BUY"
            quantity = abs(position.position)
            contract = position.contract

            order = MarketOrder(action=action, totalQuantity=quantity)

            self._logger.critical(
                "kill_switch.closing_position",
                symbol=contract.symbol,
                action=action,
                quantity=quantity,
            )

            self.ib.placeOrder(contract, order)
            closing_count += 1

        self._logger.critical(
            "kill_switch.positions_close_submitted",
            count=closing_count,
        )
        return closing_count

    async def emergency_shutdown(self) -> int:
        """Execute full emergency shutdown: cancel orders and close positions.

        Returns:
            Number of closing orders placed.
        """
        self._logger.critical("kill_switch.emergency_shutdown_initiated")
        count = await self.close_all_positions()
        self._logger.critical(
            "kill_switch.emergency_shutdown_complete",
            closing_orders=count,
        )
        return count
