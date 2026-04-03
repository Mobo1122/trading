"""Portfolio Greeks aggregation and exposure limit evaluation.

Computes portfolio-level Greeks from existing positions and checks
whether adding a proposed trade would exceed exposure caps (RISK-02).

- aggregate_portfolio_greeks: Sum position-level Greeks into portfolio totals
- evaluate_greeks_exposure: Check if a trade would breach any Greek limit
"""

from __future__ import annotations

from pydantic import BaseModel

from trading.risk.config import GreeksLimits
from trading.risk.models import GreeksImpact, RiskDecision, TradeProposal, ViolatedRule


class PortfolioGreeks(BaseModel):
    """Aggregated portfolio-level Greeks.

    Each field represents the total portfolio exposure for that Greek,
    already scaled by position quantity and contract multiplier.
    """

    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0


def aggregate_portfolio_greeks(positions: list[dict]) -> PortfolioGreeks:
    """Sum position-level Greeks into portfolio totals.

    Each position dict should contain:
    - delta, gamma, theta, vega: per-contract Greeks (from market data)
    - quantity: signed int (positive=long, negative=short)
    - multiplier: contract multiplier (100 for options, 1 for stock)

    Missing or None Greek values are treated as 0.0.
    Returns PortfolioGreeks with all zeros if positions list is empty.
    """
    total_delta = 0.0
    total_gamma = 0.0
    total_theta = 0.0
    total_vega = 0.0

    for pos in positions:
        quantity = pos.get("quantity", 0)
        multiplier = pos.get("multiplier", 1)

        total_delta += (pos.get("delta") or 0.0) * quantity * multiplier
        total_gamma += (pos.get("gamma") or 0.0) * quantity * multiplier
        total_theta += (pos.get("theta") or 0.0) * quantity * multiplier
        total_vega += (pos.get("vega") or 0.0) * quantity * multiplier

    return PortfolioGreeks(
        delta=round(total_delta, 10),
        gamma=round(total_gamma, 10),
        theta=round(total_theta, 10),
        vega=round(total_vega, 10),
    )


def evaluate_greeks_exposure(
    proposal: TradeProposal,
    limits: GreeksLimits,
    current_portfolio_greeks: PortfolioGreeks | None = None,
) -> RiskDecision | None:
    """Check if a proposed trade would push portfolio Greeks beyond limits.

    Pure function. Computes projected portfolio Greeks by adding the
    proposal's estimated impact to the current portfolio Greeks, then
    checks each Greek against its configured limit.

    Returns None if all checks pass (trade is within limits).
    Returns a RiskDecision with approved=False on the first violation.

    Check order: delta, gamma, theta, vega (short-circuits on first failure).

    Theta limit is negative -- more negative theta = worse. A projected
    theta below (more negative than) the limit triggers a violation.
    """
    current = current_portfolio_greeks or PortfolioGreeks()
    impact = proposal.estimated_greeks

    projected_delta = current.delta + impact.delta
    projected_gamma = current.gamma + impact.gamma
    projected_theta = current.theta + impact.theta
    projected_vega = current.vega + impact.vega

    # Delta check: absolute value must stay within limit
    if abs(projected_delta) > limits.max_delta:
        return RiskDecision(
            approved=False,
            violated_rule=ViolatedRule.DELTA_EXPOSURE,
            details=(
                f"Portfolio delta would be {projected_delta:.1f} "
                f"(current: {current.delta:.1f} + trade: {impact.delta:.1f}), "
                f"exceeds limit {limits.max_delta:.1f}"
            ),
            proposal_id=proposal.proposal_id,
        )

    # Gamma check: absolute value must stay within limit
    if abs(projected_gamma) > limits.max_gamma:
        return RiskDecision(
            approved=False,
            violated_rule=ViolatedRule.GAMMA_EXPOSURE,
            details=(
                f"Portfolio gamma would be {projected_gamma:.1f} "
                f"(current: {current.gamma:.1f} + trade: {impact.gamma:.1f}), "
                f"exceeds limit {limits.max_gamma:.1f}"
            ),
            proposal_id=proposal.proposal_id,
        )

    # Theta check: projected theta must not be more negative than limit
    # limit is negative (e.g. -500); theta of -600 is worse than -500
    if projected_theta < limits.max_theta:
        return RiskDecision(
            approved=False,
            violated_rule=ViolatedRule.THETA_EXPOSURE,
            details=(
                f"Portfolio theta would be {projected_theta:.1f} "
                f"(current: {current.theta:.1f} + trade: {impact.theta:.1f}), "
                f"exceeds limit {limits.max_theta:.1f}"
            ),
            proposal_id=proposal.proposal_id,
        )

    # Vega check: absolute value must stay within limit
    if abs(projected_vega) > limits.max_vega:
        return RiskDecision(
            approved=False,
            violated_rule=ViolatedRule.VEGA_EXPOSURE,
            details=(
                f"Portfolio vega would be {projected_vega:.1f} "
                f"(current: {current.vega:.1f} + trade: {impact.vega:.1f}), "
                f"exceeds limit {limits.max_vega:.1f}"
            ),
            proposal_id=proposal.proposal_id,
        )

    # All checks passed
    return None
