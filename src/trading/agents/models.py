"""Structured output contracts for all four pipeline stages.

Every agent in the pipeline produces a Pydantic model as structured output.
These contracts define the exact schema that PydanticAI validates against
the LLM response. Field descriptions are included for LLM schema generation.

Pipeline flow:
    Scanner -> ScannerOutput (list of Opportunity)
    Strategist -> StrategistOutput (list of StrategyProposal with ProposedLeg)
    Risk Manager -> RiskManagerOutput (list of RiskAssessment)
    Executor -> ExecutorOutput (list of ExecutionResult)
    Final -> PipelineResult (aggregation of all stages)
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Scanner stage
# ---------------------------------------------------------------------------


class Opportunity(BaseModel):
    """A single trading opportunity identified by the scanner agent."""

    symbol: str = Field(description="Ticker symbol of the opportunity")
    signal_type: str = Field(
        description=(
            "Type of signal detected, e.g. 'iv_rank_high', "
            "'earnings_approaching', 'technical_breakout'"
        )
    )
    confidence: float = Field(
        ge=0, le=1, description="Confidence score from 0 (low) to 1 (high)"
    )
    iv_rank: float | None = Field(
        default=None, description="Current IV rank (0-100) if available"
    )
    iv_percentile: float | None = Field(
        default=None, description="Current IV percentile (0-100) if available"
    )
    current_price: float | None = Field(
        default=None, description="Current underlying price if available"
    )
    days_to_earnings: int | None = Field(
        default=None,
        description="Days until next earnings if within lookout window",
    )
    reasoning: str = Field(
        description="Why this opportunity was flagged by the scanner"
    )


class ScannerOutput(BaseModel):
    """Structured output from the scanner agent."""

    opportunities: list[Opportunity] = Field(
        description="Identified trading opportunities ranked by confidence"
    )
    symbols_scanned: int = Field(
        description="Total number of symbols evaluated during the scan"
    )
    reasoning: str = Field(
        description="Overall scan summary and market observations"
    )


# ---------------------------------------------------------------------------
# Strategist stage
# ---------------------------------------------------------------------------


class ProposedLeg(BaseModel):
    """A single leg of a proposed options trade."""

    symbol: str = Field(description="Underlying ticker symbol")
    right: str = Field(description="Option right: 'C' (call) or 'P' (put)")
    strike: float = Field(description="Strike price")
    expiry: str = Field(
        description="Expiration date in YYYYMMDD format"
    )
    action: str = Field(description="Trade action: 'BUY' or 'SELL'")
    quantity: int = Field(description="Number of contracts")
    estimated_price: float | None = Field(
        default=None,
        description="Estimated fill price per contract if available",
    )


class StrategyProposal(BaseModel):
    """A complete trade proposal from the strategist agent."""

    symbol: str = Field(description="Underlying ticker symbol")
    strategy_type: str = Field(
        description=(
            "Strategy classification, e.g. 'iron_condor', "
            "'vertical_spread', 'covered_call'"
        )
    )
    legs: list[ProposedLeg] = Field(
        description="Individual legs comprising the strategy"
    )
    max_loss: float = Field(
        description="Maximum possible loss for the strategy in dollars"
    )
    max_profit: float = Field(
        description="Maximum possible profit for the strategy in dollars"
    )
    probability_of_profit: float = Field(
        ge=0, le=1,
        description="Estimated probability of profit from 0 to 1",
    )
    reasoning: str = Field(
        description="Why this strategy was chosen for the opportunity"
    )


class StrategistOutput(BaseModel):
    """Structured output from the strategist agent."""

    proposals: list[StrategyProposal] = Field(
        description="Trade proposals constructed from scanner opportunities"
    )
    reasoning: str = Field(
        description="Overall strategy rationale and market thesis"
    )


# ---------------------------------------------------------------------------
# Risk manager stage
# ---------------------------------------------------------------------------


class RiskAssessment(BaseModel):
    """Risk evaluation result for a single trade proposal."""

    proposal_id: str = Field(
        description="Unique ID linking back to the StrategyProposal"
    )
    deterministic_approved: bool = Field(
        description="Whether the deterministic risk engine approved the trade"
    )
    deterministic_details: str = Field(
        description="Details from the deterministic risk check"
    )
    llm_risk_score: float = Field(
        ge=1, le=10,
        description="LLM qualitative risk score from 1 (low) to 10 (high)",
    )
    llm_risk_reasoning: str = Field(
        description="LLM explanation of risk factors and concerns"
    )
    approved: bool = Field(
        description=(
            "Final approval decision: deterministic check must pass AND "
            "LLM risk score must be acceptable"
        )
    )
    reasoning: str = Field(
        description="Combined reasoning for the final approval decision"
    )


class RiskManagerOutput(BaseModel):
    """Structured output from the risk manager agent."""

    assessments: list[RiskAssessment] = Field(
        description="Risk assessments for each trade proposal"
    )
    reasoning: str = Field(
        description="Overall risk assessment summary"
    )


# ---------------------------------------------------------------------------
# Executor stage
# ---------------------------------------------------------------------------


class ExecutionResult(BaseModel):
    """Execution outcome for a single approved trade."""

    proposal_id: str = Field(
        description="Unique ID linking back to the approved proposal"
    )
    order_id: str | None = Field(
        default=None,
        description="Order ID from the execution system if submitted",
    )
    status: str = Field(
        description=(
            "Execution status: 'submitted', 'failed', or 'skipped'"
        )
    )
    details: str = Field(
        description="Human-readable details of the execution outcome"
    )


class ExecutorOutput(BaseModel):
    """Structured output from the executor agent."""

    results: list[ExecutionResult] = Field(
        description="Execution results for each approved trade"
    )
    reasoning: str = Field(
        description="Overall execution summary and any issues encountered"
    )


# ---------------------------------------------------------------------------
# Pipeline result (aggregation of all stages)
# ---------------------------------------------------------------------------


class PipelineResult(BaseModel):
    """Final aggregated result of a complete pipeline run.

    Collects outputs from all four stages. If the pipeline aborted
    early (e.g., scanner found no opportunities), later stage outputs
    are None and ``aborted_at`` records the stopping point.
    """

    run_id: str = Field(
        description="Unique identifier for this pipeline run"
    )
    scanner_output: ScannerOutput | None = Field(
        default=None, description="Scanner stage output if completed"
    )
    strategist_output: StrategistOutput | None = Field(
        default=None, description="Strategist stage output if completed"
    )
    risk_output: RiskManagerOutput | None = Field(
        default=None, description="Risk manager stage output if completed"
    )
    executor_output: ExecutorOutput | None = Field(
        default=None, description="Executor stage output if completed"
    )
    completed_stages: list[str] = Field(
        default_factory=list,
        description="Names of stages that completed successfully",
    )
    aborted_at: str | None = Field(
        default=None,
        description="Stage name where the pipeline stopped early, if any",
    )
