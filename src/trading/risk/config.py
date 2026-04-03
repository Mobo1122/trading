"""Risk limits configuration with paper/live separation.

Defines Pydantic models for all risk limit categories with Field
constraints that reject invalid values at construction time:
- PositionLimits: Per-trade size limits (dollars, contracts, portfolio %)
- GreeksLimits: Portfolio-level Greeks exposure caps
- LossLimits: Daily and weekly realized loss circuit breakers
- StrategyRestrictions: Allowed strategy types and naked option control
- RiskLimitsProfile: Complete limit set for one trading mode
- RiskLimitsConfig: Paper and live profiles
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class PositionLimits(BaseModel):
    """Per-trade position sizing limits.

    max_position_pct: Maximum trade size as fraction of account value (0-1).
    max_contracts: Maximum number of option contracts per trade.
    max_dollars: Maximum dollar exposure per trade.
    """

    max_position_pct: float = Field(default=0.05, gt=0, le=1.0)
    max_contracts: int = Field(default=10, gt=0)
    max_dollars: float = Field(default=5000.0, gt=0)


class GreeksLimits(BaseModel):
    """Portfolio-level Greeks exposure limits.

    All limits are absolute values except max_theta which is the
    maximum daily theta decay (negative number = cost per day).
    """

    max_delta: float = Field(default=500.0, gt=0)
    max_gamma: float = Field(default=100.0, gt=0)
    max_theta: float = Field(default=-500.0)  # Negative = daily decay limit
    max_vega: float = Field(default=1000.0, gt=0)


class LossLimits(BaseModel):
    """Realized loss circuit breaker thresholds.

    When cumulative realized losses exceed these limits, the circuit
    breaker halts new trade entries for the remainder of the period.
    """

    daily_max_loss: float = Field(default=1000.0, gt=0)
    weekly_max_loss: float = Field(default=3000.0, gt=0)


class StrategyRestrictions(BaseModel):
    """Controls which strategy types are permitted.

    Only strategies in allowed_strategies can be submitted.
    Naked options require explicit allow_naked_options=True.
    """

    allowed_strategies: list[str] = Field(
        default=[
            "covered_call",
            "cash_secured_put",
            "vertical_spread",
            "iron_condor",
            "iron_butterfly",
            "calendar_spread",
        ]
    )
    allow_naked_options: bool = False


class RiskLimitsProfile(BaseModel):
    """Complete risk limits for one trading mode (paper or live).

    Aggregates all limit categories plus the margin check timeout
    and emergency halt flag. The field_validator ensures no sub-config
    section is accidentally set to None.
    """

    position: PositionLimits = Field(default_factory=PositionLimits)
    greeks: GreeksLimits = Field(default_factory=GreeksLimits)
    loss: LossLimits = Field(default_factory=LossLimits)
    strategy: StrategyRestrictions = Field(default_factory=StrategyRestrictions)
    margin_check_timeout: float = Field(default=5.0, gt=0, le=30.0)
    emergency_halt: bool = False

    @field_validator("position", "greeks", "loss", mode="before")
    @classmethod
    def reject_none_subsections(cls, v: object) -> object:
        """Reject None for limit subsections -- use defaults instead."""
        if v is None:
            raise ValueError("Risk limit subsection cannot be None")
        return v


class RiskLimitsConfig(BaseModel):
    """Top-level risk config with separate paper and live profiles.

    Paper limits are typically more relaxed for testing.
    Live limits enforce stricter risk controls.
    """

    paper: RiskLimitsProfile = Field(default_factory=RiskLimitsProfile)
    live: RiskLimitsProfile = Field(default_factory=RiskLimitsProfile)
