"""Pre-trade margin check via IB whatIfOrder with timeout.

Wraps ib_async's whatIfOrderAsync with asyncio.wait_for to avoid blocking
the event loop. Parses IB's string-typed margin fields (handling the
UNSET_DOUBLE sentinel at ~1.7977e+308). Timeout is treated as pass-through,
not rejection -- a timed-out margin check does not block a trade.

Functions:
- check_margin: Async wrapper around whatIfOrderAsync with timeout
- evaluate_margin: Checks margin result for insufficient equity/margin
- _parse_margin_str: Parses IB's string margin values to float | None
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from trading.risk.models import MarginResult, RiskDecision, ViolatedRule


log = structlog.get_logger().bind(component="margin_check")

# IB uses this sentinel for unset double values (~1.7977e+308)
_IB_UNSET_DOUBLE = 1e300


def _parse_margin_str(value: str | None) -> float | None:
    """Parse an IB margin string to float, returning None for unset values.

    IB's OrderState margin fields are strings. Empty strings, None values,
    and the UNSET_DOUBLE sentinel (~1.7977e+308) all mean "not available".

    Args:
        value: Raw string from OrderState (e.g. "12345.67", "", None).

    Returns:
        Parsed float if valid and below UNSET_DOUBLE, None otherwise.
    """
    if not value:
        return None

    try:
        result = float(value)
    except (ValueError, TypeError):
        return None

    # IB UNSET_DOUBLE sentinel: any value >= 1e300 means "not set"
    if result > _IB_UNSET_DOUBLE:
        return None

    return result


async def check_margin(
    ib: Any,
    contract: Any,
    order: Any,
    timeout: float = 5.0,
) -> MarginResult:
    """Check margin impact via IB whatIfOrder with timeout.

    Calls ib.whatIfOrderAsync(contract, order) wrapped in asyncio.wait_for.
    On success, parses OrderState fields into a MarginResult. On timeout or
    any other exception, returns MarginResult(timed_out=True) -- non-blocking.

    Args:
        ib: ib_async IB instance (typed as Any to avoid coupling).
        contract: ib_async Contract for the trade.
        order: ib_async Order to simulate.
        timeout: Maximum seconds to wait for IB response (default 5.0).

    Returns:
        MarginResult with parsed fields on success, or timed_out=True on failure.
    """
    try:
        order_state = await asyncio.wait_for(
            ib.whatIfOrderAsync(contract, order),
            timeout=timeout,
        )

        # Parse commission separately -- check for UNSET_DOUBLE sentinel
        commission_raw = _parse_margin_str(order_state.commission)
        commission = commission_raw if commission_raw is not None and commission_raw < _IB_UNSET_DOUBLE else None

        return MarginResult(
            init_margin_after=_parse_margin_str(order_state.initMarginAfter),
            maint_margin_after=_parse_margin_str(order_state.maintMarginAfter),
            equity_with_loan_after=_parse_margin_str(
                order_state.equityWithLoanAfter
            ),
            commission=commission,
            warning_text=order_state.warningText or None,
            timed_out=False,
        )

    except asyncio.TimeoutError:
        log.warning(
            "Margin check timed out",
            timeout=timeout,
        )
        return MarginResult(timed_out=True)

    except Exception:
        log.warning(
            "Margin check failed",
            exc_info=True,
        )
        return MarginResult(timed_out=True)


def evaluate_margin(
    margin_result: MarginResult,
    account_value: float,
) -> RiskDecision | None:
    """Evaluate a margin check result for rejection conditions.

    Returns None if the margin check passes or timed out (pass-through).
    Returns a rejection RiskDecision if equity would go negative or
    initial margin would exceed account value.

    Args:
        margin_result: Result from check_margin().
        account_value: Current portfolio value for margin comparison.

    Returns:
        None if passed or timed out, RiskDecision with violation if failed.
    """
    # Timeout = pass-through (non-blocking)
    if margin_result.timed_out:
        return None

    # Insufficient equity: equity_with_loan_after <= 0 means margin call territory
    if (
        margin_result.equity_with_loan_after is not None
        and margin_result.equity_with_loan_after <= 0
    ):
        return RiskDecision(
            approved=False,
            violated_rule=ViolatedRule.MARGIN_INSUFFICIENT,
            details=(
                f"Equity with loan after trade would be "
                f"${margin_result.equity_with_loan_after:,.2f} "
                f"(must be > 0)"
            ),
            margin_result=margin_result,
        )

    # Margin exceeds account: initial margin > account value
    if (
        margin_result.init_margin_after is not None
        and account_value > 0
        and margin_result.init_margin_after > account_value
    ):
        return RiskDecision(
            approved=False,
            violated_rule=ViolatedRule.MARGIN_CHECK_REJECTED,
            details=(
                f"Initial margin ${margin_result.init_margin_after:,.2f} "
                f"exceeds account value ${account_value:,.2f}"
            ),
            margin_result=margin_result,
        )

    # All margin checks passed
    return None
