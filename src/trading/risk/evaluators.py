"""Pure-function evaluators for the risk engine.

Each evaluator takes a trade proposal plus limits/restrictions and returns
None if the check passes, or a RiskDecision with the first violated rule.
The RiskManager iterates evaluators in order and short-circuits on first
violation.

Evaluators in this module:
- evaluate_position_size: Dollar, contract, and portfolio-% limits
- evaluate_strategy_restrictions: Allowlist and naked options detection
- is_naked_option: Helper detecting uncovered short options
"""

from __future__ import annotations

from trading.risk.config import PositionLimits, StrategyRestrictions
from trading.risk.models import RiskDecision, TradeLeg, TradeProposal, ViolatedRule


def evaluate_position_size(
    proposal: TradeProposal,
    limits: PositionLimits,
) -> RiskDecision | None:
    """Check position sizing limits against a trade proposal.

    Evaluates in order: dollar limit, contract limit, portfolio percentage.
    Returns None if all checks pass, or a RiskDecision with the first
    violated rule.

    Args:
        proposal: Trade request with max_loss and legs.
        limits: Position sizing thresholds.

    Returns:
        None if passed, RiskDecision with violation details if failed.
    """
    max_dollar_value = proposal.max_loss

    # 1. Dollar limit
    if max_dollar_value > limits.max_dollars:
        return RiskDecision(
            approved=False,
            violated_rule=ViolatedRule.POSITION_SIZE_DOLLARS,
            details=(
                f"Max loss ${max_dollar_value:,.2f} exceeds "
                f"limit ${limits.max_dollars:,.2f}"
            ),
            proposal_id=proposal.proposal_id,
        )

    # 2. Contract limit (count only option legs)
    total_contracts = sum(
        abs(leg.quantity)
        for leg in proposal.legs
        if leg.sec_type == "OPT"
    )
    if total_contracts > limits.max_contracts:
        return RiskDecision(
            approved=False,
            violated_rule=ViolatedRule.POSITION_SIZE_CONTRACTS,
            details=(
                f"{total_contracts} contracts exceeds "
                f"limit {limits.max_contracts}"
            ),
            proposal_id=proposal.proposal_id,
        )

    # 3. Portfolio percentage
    if proposal.account_value > 0:
        pct = max_dollar_value / proposal.account_value
        if pct > limits.max_position_pct:
            return RiskDecision(
                approved=False,
                violated_rule=ViolatedRule.POSITION_SIZE_PERCENT,
                details=(
                    f"{pct:.1%} of portfolio exceeds "
                    f"limit {limits.max_position_pct:.1%}"
                ),
                proposal_id=proposal.proposal_id,
            )

    return None  # All checks passed


# ---------------------------------------------------------------------------
# Naked options detection
# ---------------------------------------------------------------------------


def is_naked_option(
    proposal: TradeProposal,
    existing_positions: list[TradeLeg] | None = None,
) -> bool:
    """Detect if a proposal contains naked (uncovered) short options.

    A short call is covered if:
    - The proposal contains a long call on the same underlying (spread), OR
    - existing_positions holds >= quantity * 100 shares of the underlying.

    A short put is covered if:
    - The proposal contains a long put on the same underlying (spread), OR
    - existing_positions holds a long put on the same underlying.

    Args:
        proposal: Trade request with legs to evaluate.
        existing_positions: Current portfolio positions (as TradeLeg-like
            objects). May be None or empty if no positions exist.

    Returns:
        True if any leg is a naked (uncovered) short option.
    """
    positions = existing_positions or []

    short_options = [
        leg for leg in proposal.legs
        if leg.sec_type == "OPT" and leg.action == "SELL"
    ]

    if not short_options:
        return False

    for short_leg in short_options:
        underlying = short_leg.symbol

        # Check if there is a covering long option in the same proposal
        has_covering_long = any(
            leg.sec_type == "OPT"
            and leg.action == "BUY"
            and leg.symbol == underlying
            for leg in proposal.legs
        )
        if has_covering_long:
            continue

        # For short calls: check if existing positions have enough stock
        if short_leg.right == "C":
            shares_held = sum(
                pos.quantity
                for pos in positions
                if pos.symbol == underlying
                and pos.sec_type == "STK"
                and pos.quantity > 0
            )
            needed_shares = abs(short_leg.quantity) * 100
            if shares_held >= needed_shares:
                continue

        # Check if existing positions have a covering long option
        has_portfolio_cover = any(
            pos.symbol == underlying
            and pos.sec_type == "OPT"
            and pos.quantity > 0  # Long position
            for pos in positions
        )
        if has_portfolio_cover:
            continue

        # This short option is naked
        return True

    return False


# ---------------------------------------------------------------------------
# Strategy restrictions evaluator
# ---------------------------------------------------------------------------


def evaluate_strategy_restrictions(
    proposal: TradeProposal,
    restrictions: StrategyRestrictions,
    existing_positions: list[TradeLeg] | None = None,
) -> RiskDecision | None:
    """Check strategy type allowlist and naked options restriction.

    Evaluates in order: strategy allowlist, then naked options.
    Returns None if all checks pass, or a RiskDecision with the first
    violated rule.

    Args:
        proposal: Trade request with strategy_type and legs.
        restrictions: Strategy restrictions configuration.
        existing_positions: Current portfolio positions for naked option
            detection. May be None.

    Returns:
        None if passed, RiskDecision with violation details if failed.
    """
    # 1. Strategy allowlist
    if proposal.strategy_type not in restrictions.allowed_strategies:
        return RiskDecision(
            approved=False,
            violated_rule=ViolatedRule.STRATEGY_RESTRICTED,
            details=(
                f"Strategy '{proposal.strategy_type}' is not allowed. "
                f"Permitted: {', '.join(restrictions.allowed_strategies)}"
            ),
            proposal_id=proposal.proposal_id,
        )

    # 2. Naked options check
    if not restrictions.allow_naked_options:
        if is_naked_option(proposal, existing_positions):
            return RiskDecision(
                approved=False,
                violated_rule=ViolatedRule.NAKED_OPTION,
                details=(
                    "Proposal contains naked (uncovered) short options "
                    "and allow_naked_options is disabled"
                ),
                proposal_id=proposal.proposal_id,
            )

    return None  # All checks passed
