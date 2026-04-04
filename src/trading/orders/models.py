"""Pydantic domain models for order execution tracking.

Defines the shared vocabulary for execution and slippage analysis:
- ExecutionRecord: Domain model for a single fill execution
- SlippageReport: Summary of slippage for a completed order
- calculate_slippage: Utility for slippage computation
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ExecutionRecord(BaseModel):
    """Domain model for a single fill execution.

    Maps to the execution_records DB table. Captures fill details
    from IB's Execution and CommissionReport objects, plus slippage
    relative to the expected mid-market price at submission time.
    """

    exec_id: str
    order_id: str
    side: str  # "BOT" or "SLD"
    quantity: float
    price: float
    avg_price: float
    cum_qty: float
    commission: float | None = None
    realized_pnl: float | None = None
    exchange: str = ""
    liquidity: int | None = None
    timestamp: datetime | None = None
    expected_price: float | None = None
    slippage: float | None = None
    slippage_bps: float | None = None


class SlippageReport(BaseModel):
    """Slippage calculation for a completed order.

    Summarises the slippage for the entire order (all fills combined).
    Positive values are always unfavorable: paid more on BUY, received
    less on SELL.
    """

    order_id: str
    action: str  # "BUY" or "SELL"
    expected_price: float
    avg_fill_price: float
    quantity: float
    slippage_dollars: float  # positive = unfavorable
    slippage_bps: float  # basis points


def calculate_slippage(
    action: str,
    expected_price: float,
    fill_price: float,
    quantity: float,
) -> tuple[float, float]:
    """Calculate slippage in dollars and basis points.

    Returns (slippage_dollars, slippage_bps).
    Positive = unfavorable (paid more on BUY, received less on SELL).

    Args:
        action: "BUY" or "SELL"
        expected_price: Mid-market price at time of order submission.
        fill_price: Actual fill price (or average fill price).
        quantity: Number of contracts/shares filled.

    Returns:
        Tuple of (slippage_dollars, slippage_bps).
    """
    if action == "BUY":
        slippage_dollars = (fill_price - expected_price) * quantity
    else:  # SELL
        slippage_dollars = (expected_price - fill_price) * quantity

    # Basis points relative to expected price
    if expected_price != 0:
        slippage_bps = (
            (fill_price - expected_price) / expected_price
        ) * 10000
        if action == "SELL":
            slippage_bps = -slippage_bps  # Normalize: positive = unfavorable
    else:
        slippage_bps = 0.0

    # Round to 10 decimal places to avoid IEEE 754 float noise
    # (consistent with Phase 3 Greeks rounding pattern, 03-03 decision)
    return round(slippage_dollars, 10), round(slippage_bps, 10)
