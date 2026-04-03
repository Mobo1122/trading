"""Pydantic domain models for the risk engine.

Defines the shared vocabulary for risk evaluation:
- TradeProposal: Incoming trade request to be evaluated
- TradeLeg: Individual leg of a multi-leg trade
- GreeksImpact: Estimated portfolio Greeks change from a trade
- RiskDecision: Approve/reject result with reason and details
- ViolatedRule: Enumeration of all possible rejection reasons
- MarginResult: IB margin check response data
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ViolatedRule(str, enum.Enum):
    """All possible reasons a trade proposal can be rejected.

    Each value maps to a specific risk check in the evaluation pipeline.
    The string values are stored in the risk_decisions database table.
    """

    POSITION_SIZE_DOLLARS = "POSITION_SIZE_DOLLARS"
    POSITION_SIZE_CONTRACTS = "POSITION_SIZE_CONTRACTS"
    POSITION_SIZE_PERCENT = "POSITION_SIZE_PERCENT"
    DELTA_EXPOSURE = "DELTA_EXPOSURE"
    GAMMA_EXPOSURE = "GAMMA_EXPOSURE"
    THETA_EXPOSURE = "THETA_EXPOSURE"
    VEGA_EXPOSURE = "VEGA_EXPOSURE"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    WEEKLY_LOSS_LIMIT = "WEEKLY_LOSS_LIMIT"
    STRATEGY_RESTRICTED = "STRATEGY_RESTRICTED"
    NAKED_OPTION = "NAKED_OPTION"
    MARGIN_INSUFFICIENT = "MARGIN_INSUFFICIENT"
    MARGIN_CHECK_REJECTED = "MARGIN_CHECK_REJECTED"
    RISK_MANAGER_UNAVAILABLE = "RISK_MANAGER_UNAVAILABLE"
    CIRCUIT_BREAKER_ACTIVE = "CIRCUIT_BREAKER_ACTIVE"
    EMERGENCY_HALT = "EMERGENCY_HALT"


class TradeLeg(BaseModel):
    """A single leg of a trade proposal.

    Represents one instrument action (buy/sell) within a potentially
    multi-leg options strategy. The contract and order fields hold
    ib_async objects when available, typed as Any to avoid coupling.
    """

    symbol: str
    sec_type: str  # STK or OPT
    action: str  # BUY or SELL
    quantity: int
    right: str | None = None  # C or P (options only)
    strike: float | None = None  # options only
    expiry: str | None = None  # options only, YYYYMMDD format
    contract: Any | None = None  # ib_async Contract
    order: Any | None = None  # ib_async Order


class GreeksImpact(BaseModel):
    """Estimated portfolio Greeks change from executing a trade.

    Values represent the NET change to portfolio Greeks, not absolute
    levels. Positive delta = more long exposure, negative theta =
    more time decay cost.
    """

    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0


class TradeProposal(BaseModel):
    """A trade request submitted to the risk engine for evaluation.

    Contains all information needed for risk checks: the trade legs,
    estimated Greeks impact, worst-case loss, strategy classification,
    and current account value for percentage-based limits.
    """

    proposal_id: str = Field(default_factory=lambda: str(uuid4()))
    legs: list[TradeLeg]
    estimated_greeks: GreeksImpact
    max_loss: float  # Caller-computed worst-case loss
    strategy_type: str  # e.g. "covered_call", "iron_condor"
    account_value: float  # Current portfolio value for % calculations


class MarginResult(BaseModel):
    """Response from an IB margin check (whatIfOrder).

    Captures the projected margin impact of a trade. Fields are None
    when IB doesn't return the value. timed_out indicates the margin
    check exceeded the configured timeout.
    """

    init_margin_after: float | None = None
    maint_margin_after: float | None = None
    equity_with_loan_after: float | None = None
    commission: float | None = None
    warning_text: str | None = None
    timed_out: bool = False


class RiskDecision(BaseModel):
    """Result of evaluating a TradeProposal against risk rules.

    approved=True means the trade passed all checks.
    approved=False includes the violated_rule and human-readable details.
    dry_run=True means the decision was logged but not enforced.
    """

    approved: bool
    violated_rule: ViolatedRule | None = None
    details: str = ""
    proposal_id: str = ""
    evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    margin_result: MarginResult | None = None
    dry_run: bool = False
