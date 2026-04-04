"""Agent configuration for the trading pipeline.

Defines per-agent model selection, temperature, token limits, and
checkpoint connection string. Integrates into the main Settings class
via the ``agents`` field.

Each agent can override the default model by setting its specific field
(e.g., ``scanner_model``). If not set, the agent falls back to the
shared ``model`` default.

The checkpoint connection string MUST use psycopg format
(``postgresql://``), NOT asyncpg (``postgresql+asyncpg://``).
See RESEARCH.md Pitfall 1 for details.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RegimeConfig(BaseModel):
    """Configuration for market regime detection.

    Controls the thresholds and hysteresis behavior of the regime
    detector. Regime detection classifies market conditions into one
    of 6 regimes (BULL_QUIET, BULL_VOLATILE, BEAR_QUIET, BEAR_VOLATILE,
    SIDEWAYS, UNKNOWN) to adapt strategy selection to current conditions.

    Attributes:
        enabled: Whether regime detection is active.
        hysteresis_count: Regime must persist N consecutive checks before
            switching (prevents whiplash).
        iv_rank_high_threshold: IV rank above this signals high volatility.
        iv_rank_low_threshold: IV rank below this signals low volatility.
        momentum_lookback_days: Number of price data points for momentum.
        momentum_bull_threshold: Momentum above this signals bullish trend.
        momentum_bear_threshold: Momentum below this signals bearish trend.
        vix_high_threshold: VIX above this signals high volatility.
        vix_low_threshold: VIX below this signals low volatility.
    """

    enabled: bool = True
    hysteresis_count: int = Field(
        default=3,
        ge=1,
        description="Regime must persist N consecutive checks before switching",
    )
    iv_rank_high_threshold: float = Field(
        default=60.0,
        description="IV rank above this = high volatility signal",
    )
    iv_rank_low_threshold: float = Field(
        default=30.0,
        description="IV rank below this = low volatility signal",
    )
    momentum_lookback_days: int = Field(
        default=20,
        ge=5,
        description="Number of price data points for momentum calculation",
    )
    momentum_bull_threshold: float = Field(
        default=0.02,
        description="Price momentum > this = bullish trend signal",
    )
    momentum_bear_threshold: float = Field(
        default=-0.02,
        description="Price momentum < this = bearish trend signal",
    )
    vix_high_threshold: float = Field(
        default=25.0,
        description="VIX above this = high volatility (if VIX available)",
    )
    vix_low_threshold: float = Field(
        default=15.0,
        description="VIX below this = low volatility (if VIX available)",
    )


class RollingConfig(BaseModel):
    """Configuration for option position rolling logic.

    Controls when expiring positions are identified for rolling, the
    loss threshold beyond which a position should be closed rather than
    rolled, and the target DTE for the replacement leg.

    Attributes:
        enabled: Whether automatic rolling evaluation is active.
        dte_threshold: Roll positions with DTE <= this value.
        max_loss_multiple: Don't roll if unrealized loss exceeds
            this multiple of original credit received (close instead).
        preferred_roll_dte: Target DTE for the new position after rolling.
        allow_strike_adjustment: Allow rolling to a different strike
            if position is ITM.
        max_roll_attempts: Maximum consecutive rolls for the same
            position before requiring manual review.
    """

    enabled: bool = True
    dte_threshold: int = Field(
        default=7,
        ge=1,
        le=30,
        description="Roll positions with DTE <= this value",
    )
    max_loss_multiple: float = Field(
        default=2.0,
        gt=0,
        description="Don't roll if unrealized loss > this * original credit",
    )
    preferred_roll_dte: int = Field(
        default=30,
        ge=7,
        description="Target DTE for the new position after rolling",
    )
    allow_strike_adjustment: bool = Field(
        default=True,
        description="Allow rolling to a different strike",
    )
    max_roll_attempts: int = Field(
        default=3,
        ge=1,
        description="Maximum consecutive rolls for the same position",
    )


class AgentConfig(BaseModel):
    """Configuration for the AI agent pipeline.

    Attributes:
        model: Default LLM model for all agents (PydanticAI model string).
        scanner_model: Override model for the scanner agent.
        strategist_model: Override model for the strategist agent.
        risk_model: Override model for the risk manager agent.
        executor_model: Override model for the executor agent.
        temperature: LLM sampling temperature (low for consistent outputs).
        max_tokens: Maximum tokens per LLM response.
        request_limit: PydanticAI UsageLimits.request_limit per agent run.
        response_tokens_limit: PydanticAI UsageLimits.response_tokens_limit.
        checkpoint_conn_string: psycopg connection string for LangGraph
            checkpoint persistence. Must NOT contain ``+asyncpg``.
        regime: Market regime detection configuration (thresholds,
            hysteresis). See :class:`RegimeConfig`.
        rolling: Option position rolling configuration (DTE thresholds,
            loss limits, target DTE). See :class:`RollingConfig`.
    """

    model: str = "anthropic:claude-sonnet-4-6"
    scanner_model: str | None = None
    strategist_model: str | None = None
    risk_model: str | None = None
    executor_model: str | None = None
    temperature: float = 0.1
    max_tokens: int = 2000
    request_limit: int = 10
    response_tokens_limit: int = 4000
    checkpoint_conn_string: str = (
        "postgresql://trading:trading@localhost:5432/trading"
    )
    regime: RegimeConfig = RegimeConfig()
    rolling: RollingConfig = RollingConfig()

    def get_model(self, agent_name: str) -> str:
        """Return the model for a specific agent, falling back to default.

        Args:
            agent_name: One of "scanner", "strategist", "risk", "executor".

        Returns:
            The agent-specific model override if set, otherwise the default
            ``model`` value.
        """
        override_map = {
            "scanner": self.scanner_model,
            "strategist": self.strategist_model,
            "risk": self.risk_model,
            "executor": self.executor_model,
        }
        override = override_map.get(agent_name)
        return override if override is not None else self.model
