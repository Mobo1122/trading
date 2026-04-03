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
