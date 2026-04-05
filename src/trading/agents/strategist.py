"""Strategist PydanticAI agent for constructing options trade proposals.

The strategist takes scanner-identified opportunities and constructs complete
trade proposals with strategy type, strikes, expirations, and sizing. It
selects ONLY from real available option chain data via the ContractResolver
tool -- never inventing strike prices or expirations.

Each tool wraps a real service interface (ContractResolver, Redis, RiskLimits)
with error handling that returns JSON error messages instead of raising
exceptions -- the LLM can interpret errors and adjust its strategy.

Exports:
    strategist_agent: PydanticAI Agent instance with registered tools.
    StrategistDeps: Dataclass for dependency injection into tools.
    run_strategist: Async helper that runs the strategist with usage limits.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import structlog
from pydantic_ai import Agent, ModelSettings, RunContext, UsageLimits
from pydantic_ai.usage import Usage

from trading.agents.models import StrategistOutput
from trading.config import Settings
from trading.risk.config import RiskLimitsProfile

log = structlog.get_logger("trading.agents.strategist")


# ---------------------------------------------------------------------------
# Dependency injection container
# ---------------------------------------------------------------------------


@dataclass
class StrategistDeps:
    """Dependencies injected into strategist agent tools.

    Attributes:
        contract_resolver: ContractResolver for looking up real option chains
            (available strikes, expirations) via IB API with Redis caching.
        iv_engine: IV rank/percentile computation engine.
        redis_client: Async Redis client for latest market data lookup
            via ``HGET mktdata:latest:quote:{symbol}``.
        risk_limits: Active risk limits profile (paper or live) that
            constrains position sizing and strategy selection.
        account_value: Current account value in dollars for position
            sizing calculations.
        opportunities: Scanner-identified opportunities as list of dicts
            (serialized Opportunity models from the pipeline state).
        settings: Application settings for agent configuration.
    """

    contract_resolver: Any  # ContractResolver from Phase 1
    iv_engine: Any  # IVEngine from Phase 2
    redis_client: Any
    risk_limits: RiskLimitsProfile
    account_value: float
    opportunities: list[dict]
    settings: Settings


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------

strategist_agent = Agent(
    model=None,  # Set at runtime from config in run_strategist
    output_type=StrategistOutput,
    deps_type=StrategistDeps,
    instructions=(
        "You are an options strategist for an autonomous trading system. "
        "Your job is to take trading opportunities from the scanner and "
        "construct complete, executable trade proposals.\n\n"
        "CRITICAL RULES:\n"
        "1. You MUST use the get_option_chain tool to retrieve available "
        "strikes and expirations for each symbol BEFORE proposing any trade. "
        "NEVER invent strike prices or expiration dates.\n"
        "2. Select strikes FROM the available chain data only.\n"
        "3. Check risk limits before sizing -- respect max contracts, "
        "max dollars, and max position percentage.\n"
        "4. Include max_loss, max_profit, and probability_of_profit for "
        "every proposal.\n\n"
        "Strategy selection guidelines:\n"
        "- High IV rank (>60): Consider premium-selling strategies "
        "(iron condors, vertical credit spreads, covered calls)\n"
        "- Low IV rank (<30): Consider premium-buying strategies "
        "(vertical debit spreads, long options)\n"
        "- Near earnings: Consider straddles/strangles for volatility "
        "plays, or avoid if risk is too high\n"
        "- Always prefer defined-risk strategies (spreads) over naked "
        "positions unless explicitly allowed\n\n"
        "For each proposal, explain your reasoning: why this strategy, "
        "why these strikes, why this expiration, and why this size."
    ),
    model_settings=ModelSettings(temperature=0.1, max_tokens=2000),
)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@strategist_agent.tool
async def get_option_chain(ctx: RunContext[StrategistDeps], symbol: str) -> str:
    """Get the full option chain for a symbol with available strikes and expirations.

    Returns JSON with exchange, trading_class, multiplier, expirations
    (list of YYYYMMDD strings), and strikes (list of floats). You MUST
    select strikes and expirations from these lists only.
    """
    try:
        chain = await ctx.deps.contract_resolver.get_option_chain(symbol)
        # Summarize to reduce token usage: include all expirations but
        # limit strikes to a manageable window around current price
        summary = {
            "symbol": chain.get("symbol", symbol),
            "exchange": chain.get("exchange"),
            "multiplier": chain.get("multiplier", "100"),
            "expirations": chain.get("expirations", []),
            "strikes": chain.get("strikes", []),
            "num_expirations": len(chain.get("expirations", [])),
            "num_strikes": len(chain.get("strikes", [])),
        }
        return json.dumps(summary)
    except Exception as exc:
        log.warning("tool.get_option_chain.error", symbol=symbol, error=str(exc))
        return json.dumps({"error": str(exc), "symbol": symbol})


@strategist_agent.tool
async def get_current_price(ctx: RunContext[StrategistDeps], symbol: str) -> str:
    """Get the current market price for a symbol from Redis.

    Returns JSON with bid, ask, last price, and implied volatility.
    Use this to determine appropriate strike selection relative to
    the current underlying price.
    """
    try:
        data = await ctx.deps.redis_client.hgetall(f"mktdata:latest:quote:{symbol}")
        if not data:
            return json.dumps(
                {"symbol": symbol, "error": "No market data available"}
            )
        # Return relevant pricing fields
        price_data = {
            "symbol": symbol,
            "bid": data.get("bid"),
            "ask": data.get("ask"),
            "last": data.get("last"),
            "implied_volatility": data.get("implied_volatility"),
        }
        return json.dumps(price_data)
    except Exception as exc:
        log.warning(
            "tool.get_current_price.error", symbol=symbol, error=str(exc)
        )
        return json.dumps({"error": str(exc), "symbol": symbol})


@strategist_agent.tool
async def get_risk_limits(ctx: RunContext[StrategistDeps]) -> str:
    """Get the active risk limits that constrain position sizing and strategy selection.

    Returns JSON with position limits (max contracts, max dollars,
    max portfolio percentage), allowed strategy types, and whether
    naked options are permitted. All proposals must respect these limits.
    """
    try:
        limits = ctx.deps.risk_limits
        return json.dumps({
            "account_value": ctx.deps.account_value,
            "position": {
                "max_position_pct": limits.position.max_position_pct,
                "max_contracts": limits.position.max_contracts,
                "max_dollars": limits.position.max_dollars,
                "max_dollar_from_pct": round(
                    ctx.deps.account_value * limits.position.max_position_pct, 2
                ),
            },
            "greeks": {
                "max_delta": limits.greeks.max_delta,
                "max_gamma": limits.greeks.max_gamma,
                "max_theta": limits.greeks.max_theta,
                "max_vega": limits.greeks.max_vega,
            },
            "strategy": {
                "allowed_strategies": limits.strategy.allowed_strategies,
                "allow_naked_options": limits.strategy.allow_naked_options,
            },
        })
    except Exception as exc:
        log.warning("tool.get_risk_limits.error", error=str(exc))
        return json.dumps({"error": str(exc)})


@strategist_agent.tool
async def get_opportunities(ctx: RunContext[StrategistDeps]) -> str:
    """Get the scanner-identified trading opportunities.

    Returns JSON array of opportunity dicts with symbol, signal_type,
    confidence, iv_rank, current_price, days_to_earnings, and reasoning.
    Use these as input for constructing trade proposals.
    """
    try:
        return json.dumps(ctx.deps.opportunities)
    except Exception as exc:
        log.warning("tool.get_opportunities.error", error=str(exc))
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Run helper
# ---------------------------------------------------------------------------


async def run_strategist(
    deps: StrategistDeps,
    model: str | None = None,
    usage_limits: UsageLimits | None = None,
) -> tuple[StrategistOutput, Usage, list]:
    """Run the strategist agent with usage limits and structured output.

    Args:
        deps: Dependency container with contract resolver, IV engine,
            Redis client, risk limits, account value, opportunities,
            and settings.
        model: PydanticAI model string override. If None, uses the
            strategist-specific model from agent config (or default model).
        usage_limits: Token/request limits. Defaults to
            ``UsageLimits(request_limit=15, response_tokens_limit=4000)``.

    Returns:
        Tuple of (StrategistOutput, Usage, all_messages) where:
        - StrategistOutput: Validated structured output with trade proposals.
        - Usage: Token usage statistics for the run.
        - all_messages: Full message history for audit logging.
    """
    agent_config = deps.settings.agents
    resolved_model = model or agent_config.get_model("strategist")

    if usage_limits is None:
        usage_limits = UsageLimits(
            request_limit=15,
            response_tokens_limit=agent_config.response_tokens_limit,
        )

    num_opportunities = len(deps.opportunities)
    symbols = list({opp.get("symbol", "?") for opp in deps.opportunities})

    prompt = (
        f"Construct trade proposals for {num_opportunities} scanner "
        f"opportunities across symbols: {', '.join(symbols)}. "
        f"Use your tools to get the option chain, current price, and risk "
        f"limits for each symbol. Select strikes and expirations from "
        f"real available data only. Size positions within risk limits."
    )

    log.info(
        "strategist.run.start",
        num_opportunities=num_opportunities,
        symbols=symbols,
        model=resolved_model,
        request_limit=usage_limits.request_limit,
    )

    result = await strategist_agent.run(
        prompt,
        deps=deps,
        model=resolved_model,
        usage_limits=usage_limits,
    )

    log.info(
        "strategist.run.complete",
        num_proposals=len(result.output.proposals),
        request_tokens=result.usage().request_tokens,
        response_tokens=result.usage().response_tokens,
    )

    return result.output, result.usage(), result.all_messages()
