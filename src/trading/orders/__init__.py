"""Order lifecycle management: state machine, tracking, and execution.

Provides the OrderStateMachine for deterministic state transitions,
OrderTracker for IB event integration with database persistence,
ComboOrderBuilder for multi-leg BAG contract construction, and
Pydantic execution models for fill/slippage tracking.
"""

from trading.orders.combo_builder import ComboOrderBuilder
from trading.orders.models import ExecutionRecord, SlippageReport, calculate_slippage
from trading.orders.state_machine import OrderStateMachine
from trading.orders.tracker import OrderTracker

__all__ = [
    "ComboOrderBuilder",
    "ExecutionRecord",
    "OrderStateMachine",
    "OrderTracker",
    "SlippageReport",
    "calculate_slippage",
]
