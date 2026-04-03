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
