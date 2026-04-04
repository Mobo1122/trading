"""Order lifecycle management: state machine, tracking, execution, and recovery.

Provides the OrderStateMachine for deterministic state transitions,
OrderTracker for IB event integration with database persistence,
OrderExecutionService as the risk-gated entry point for all order
placement, ComboOrderBuilder for multi-leg BAG contract construction,
FillTracker for event-driven fill recording with slippage measurement,
OrderRecoveryManager for post-reconnect order reconciliation,
and Pydantic execution models for fill/slippage tracking.
"""

from trading.orders.combo_builder import ComboOrderBuilder
from trading.orders.execution_service import OrderExecutionService
from trading.orders.fill_tracker import FillTracker
from trading.orders.models import ExecutionRecord, SlippageReport, calculate_slippage
from trading.orders.recovery import OrderRecoveryManager
from trading.orders.state_machine import OrderStateMachine
from trading.orders.tracker import OrderTracker

__all__ = [
    "ComboOrderBuilder",
    "ExecutionRecord",
    "FillTracker",
    "OrderExecutionService",
    "OrderRecoveryManager",
    "OrderStateMachine",
    "OrderTracker",
    "SlippageReport",
    "calculate_slippage",
]
