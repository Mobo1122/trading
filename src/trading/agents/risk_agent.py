"""Risk manager PydanticAI agent layered on the deterministic risk engine.

The risk agent enforces a strict deterministic-first architecture:
1. FIRST: Run the Phase 3 RiskManager deterministic check (non-negotiable)
2. THEN: LLM provides qualitative risk assessment on top

The agent NEVER bypasses or overrides the deterministic risk gate. A proposal
is approved only if both the deterministic check passes AND the LLM risk
score is acceptable (<= 7).

Greeks lookup: Before running the deterministic check, the agent fetches
real Greeks from the Phase 2 Redis market data cache (HSET keys
``mktdata:latest:greeks:{con_id}``). Per-leg Greeks are aggregated
(quantity-weighted, sign-adjusted for BUY/SELL) into a GreeksImpact so
the Phase 3 RISK-02 Greek exposure check evaluates actual portfolio impact.
Falls back to zero Greeks with a structlog warning only on cache miss.

Exports:
    risk_agent: PydanticAI Agent instance with registered tools.
    RiskAgentDeps: Dataclass for dependency injection into tools.
    run_risk_agent: Async helper that runs the risk agent with usage limits.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import structlog
from pydantic_ai import Agent, ModelSettings, RunContext, UsageLimits
from pydantic_ai.usage import Usage

from trading.agents.models import RiskManagerOutput
from trading.config import Settings
from trading.risk.manager import RiskManager
from trading.risk.models import GreeksImpact, TradeLeg, TradeProposal

log = structlog.get_logger("trading.agents.risk_agent")


# ---------------------------------------------------------------------------
# Dependency injection container
# ---------------------------------------------------------------------------


@dataclass
class RiskAgentDeps:
    """Dependencies injected into risk agent tools.

    Attributes:
        risk_manager: Phase 3 deterministic risk engine for hard rule checks.
        redis_client: Async Redis client for Greeks lookup from the
            Phase 2 market data cache (``mktdata:latest:greeks:{con_id}``).
        session_factory: SQLAlchemy async session factory for DB access.
        trade_proposals: Strategist output proposals from pipeline state.
        settings: Application settings for agent configuration.
    """

    risk_manager: RiskManager
    redis_client: Any
    session_factory: Any
    trade_proposals: list[dict] = field(default_factory=list)
    settings: Settings = field(default_factory=Settings)


# ---------------------------------------------------------------------------
# Private helper: Greeks lookup from Redis cache
# ---------------------------------------------------------------------------


async def _lookup_greeks(
    redis_client: Any,
    symbol: str,
    strike: float,
    expiry: str,
    right: str,
) -> dict:
    """Look up real-time Greeks from the Phase 2 Redis market data cache.

    Scans ``mktdata:latest:greeks:*`` HSET keys and matches by symbol.
    This is efficient because only actively-subscribed contracts have cached
    Greeks -- typically <100 keys.

    Known simplification: matching by symbol alone does not distinguish
    between contracts at different strikes/expiries. A future enhancement
    can add con_id resolution via ContractResolver.qualify_options() for
    exact matching. For now, same-symbol Greeks provide a reasonable
    approximation for portfolio-level exposure checks.

    Args:
        redis_client: Async Redis client (decode_responses=True).
        symbol: Underlying ticker symbol to match.
        strike: Strike price (logged for diagnostics, not matched).
        expiry: Expiration date YYYYMMDD (logged for diagnostics).
        right: Option right C or P (logged for diagnostics).

    Returns:
        Dict with keys: found (bool), delta, gamma, theta, vega (float).
    """
    zero_fallback = {
        "found": False,
        "delta": 0.0,
        "gamma": 0.0,
        "theta": 0.0,
        "vega": 0.0,
    }

    try:
        cursor = "0"
        while True:
            cursor, keys = await redis_client.scan(
                cursor=cursor, match="mktdata:latest:greeks:*", count=100
            )
            for key in keys:
                data = await redis_client.hgetall(key)
                if not data:
                    continue
                if data.get("symbol") == symbol:
                    log.debug(
                        "greeks.cache_hit",
                        symbol=symbol,
                        strike=strike,
                        expiry=expiry,
                        right=right,
                        redis_key=key,
                    )
                    return {
                        "found": True,
                        "delta": float(data.get("delta", 0) or 0),
                        "gamma": float(data.get("gamma", 0) or 0),
                        "theta": float(data.get("theta", 0) or 0),
                        "vega": float(data.get("vega", 0) or 0),
                    }

            # cursor returns to "0" when scan is complete
            if cursor == 0 or cursor == "0":
                break

        # No match found
        log.warning(
            "greeks.cache_miss",
            symbol=symbol,
            strike=strike,
            expiry=expiry,
            right=right,
        )
        return zero_fallback

    except Exception as exc:
        log.warning(
            "greeks.redis_error",
            symbol=symbol,
            strike=strike,
            expiry=expiry,
            right=right,
            error=str(exc),
        )
        return zero_fallback


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------

risk_agent = Agent(
    model=None,  # Set at runtime from config in run_risk_agent
    output_type=RiskManagerOutput,
    deps_type=RiskAgentDeps,
    instructions=(
        "You are an options trading risk manager. For each trade proposal:\n"
        "1. FIRST: Run the deterministic risk check tool -- this is "
        "non-negotiable, every proposal must pass deterministic rules\n"
        "2. THEN: Provide your qualitative risk assessment considering "
        "market conditions, strategy appropriateness, and overall "
        "portfolio impact\n"
        "3. Score risk 1-10 (1=lowest risk, 10=highest risk)\n"
        "4. A proposal is approved ONLY IF: deterministic check passes "
        "AND your risk score is <= 7\n"
        "5. NEVER approve a proposal that failed the deterministic risk "
        "check, regardless of your own assessment\n"
        "Your role is to ADD a layer of judgment on top of hard rules, "
        "not to override them."
    ),
    model_settings=ModelSettings(temperature=0.1, max_tokens=2000),
)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@risk_agent.tool
async def get_contract_greeks(
    ctx: RunContext[RiskAgentDeps],
    symbol: str,
    strike: float,
    expiry: str,
    right: str,
) -> str:
    """Look up real-time Greeks from the Redis market data cache for an option.

    Returns JSON with delta, gamma, theta, vega values from the Phase 2
    market data cache. Returns zero Greeks with found=false if no cached
    data exists for the symbol.
    """
    result = await _lookup_greeks(
        ctx.deps.redis_client, symbol, strike, expiry, right
    )
    return json.dumps(result)


@risk_agent.tool
async def check_deterministic_risk(
    ctx: RunContext[RiskAgentDeps],
    proposal_json: str,
) -> str:
    """Run the Phase 3 deterministic risk check on a trade proposal.

    Parses the proposal, fetches real Greeks from Redis for each leg,
    aggregates into GreeksImpact, and runs RiskManager.check_trade().
    This is the NON-NEGOTIABLE first step for every proposal.
    """
    try:
        proposal_data = json.loads(proposal_json)

        # Build TradeLeg objects from StrategyProposal legs
        legs = []
        for leg_data in proposal_data.get("legs", []):
            legs.append(
                TradeLeg(
                    symbol=leg_data.get("symbol", ""),
                    sec_type="OPT",
                    action=leg_data.get("action", "BUY"),
                    quantity=leg_data.get("quantity", 1),
                    right=leg_data.get("right"),
                    strike=leg_data.get("strike"),
                    expiry=leg_data.get("expiry"),
                )
            )

        # Fetch real Greeks for each leg and aggregate into GreeksImpact
        sum_delta = 0.0
        sum_gamma = 0.0
        sum_theta = 0.0
        sum_vega = 0.0

        for leg in legs:
            greeks = await _lookup_greeks(
                ctx.deps.redis_client,
                symbol=leg.symbol,
                strike=leg.strike or 0.0,
                expiry=leg.expiry or "",
                right=leg.right or "",
            )
            quantity = leg.quantity
            # Negate for SELL actions since selling reduces exposure
            sign = -1 if leg.action == "SELL" else 1

            sum_delta += greeks["delta"] * quantity * sign
            sum_gamma += greeks["gamma"] * quantity * sign
            sum_theta += greeks["theta"] * quantity * sign
            sum_vega += greeks["vega"] * quantity * sign

        estimated_greeks = GreeksImpact(
            delta=round(sum_delta, 10),
            gamma=round(sum_gamma, 10),
            theta=round(sum_theta, 10),
            vega=round(sum_vega, 10),
        )

        log.info(
            "risk.greeks_aggregated",
            proposal_symbol=proposal_data.get("symbol", "unknown"),
            num_legs=len(legs),
            delta=estimated_greeks.delta,
            gamma=estimated_greeks.gamma,
            theta=estimated_greeks.theta,
            vega=estimated_greeks.vega,
        )

        # Construct the TradeProposal for the risk manager
        trade_proposal = TradeProposal(
            legs=legs,
            estimated_greeks=estimated_greeks,
            max_loss=proposal_data.get("max_loss", 0.0),
            strategy_type=proposal_data.get("strategy_type", "unknown"),
            account_value=proposal_data.get("account_value", 100000.0),
        )

        # Run the deterministic risk check
        decision = await ctx.deps.risk_manager.check_trade(trade_proposal)

        return json.dumps({
            "approved": decision.approved,
            "violated_rule": (
                decision.violated_rule.value
                if decision.violated_rule
                else None
            ),
            "details": decision.details,
            "proposal_id": decision.proposal_id,
        })

    except Exception as exc:
        log.warning(
            "risk.deterministic_check_failed",
            error=str(exc),
            exc_info=True,
        )
        return json.dumps({
            "approved": False,
            "violated_rule": "RISK_MANAGER_UNAVAILABLE",
            "details": f"Deterministic risk check failed: {exc}",
            "proposal_id": "",
        })


@risk_agent.tool
async def get_trade_proposals(ctx: RunContext[RiskAgentDeps]) -> str:
    """Get the list of trade proposals to evaluate.

    Returns JSON array of all proposals from the strategist stage.
    """
    return json.dumps(ctx.deps.trade_proposals)


# ---------------------------------------------------------------------------
# Run helper
# ---------------------------------------------------------------------------


async def run_risk_agent(
    deps: RiskAgentDeps,
    model: str | None = None,
    usage_limits: UsageLimits | None = None,
) -> tuple[RiskManagerOutput, Usage, list]:
    """Run the risk agent with usage limits and structured output.

    Args:
        deps: Dependency container with risk manager, Redis client,
            trade proposals, and settings.
        model: PydanticAI model string override. If None, uses the
            risk-specific model from agent config (or default model).
        usage_limits: Token/request limits. Defaults to
            ``UsageLimits(request_limit=10, response_tokens_limit=4000)``.

    Returns:
        Tuple of (RiskManagerOutput, Usage, all_messages) where:
        - RiskManagerOutput: Validated structured output with assessments.
        - Usage: Token usage statistics for the run.
        - all_messages: Full message history for audit logging.
    """
    agent_config = deps.settings.agents
    resolved_model = model or agent_config.get_model("risk")

    if usage_limits is None:
        usage_limits = UsageLimits(
            request_limit=agent_config.request_limit,
            response_tokens_limit=agent_config.response_tokens_limit,
        )

    # Build a summary of proposals for the prompt
    proposal_summaries = []
    for i, p in enumerate(deps.trade_proposals):
        symbol = p.get("symbol", "unknown")
        strategy = p.get("strategy_type", "unknown")
        num_legs = len(p.get("legs", []))
        max_loss = p.get("max_loss", 0)
        proposal_summaries.append(
            f"  {i + 1}. {symbol} {strategy} ({num_legs} legs, "
            f"max_loss=${max_loss:.0f})"
        )

    summary = "\n".join(proposal_summaries) if proposal_summaries else "None"

    prompt = (
        f"Evaluate the following trade proposals against risk rules:\n"
        f"{summary}\n\n"
        f"For EACH proposal, first run the deterministic risk check, "
        f"then provide your assessment."
    )

    log.info(
        "risk_agent.run.start",
        num_proposals=len(deps.trade_proposals),
        model=resolved_model,
        request_limit=usage_limits.request_limit,
    )

    result = await risk_agent.run(
        prompt,
        deps=deps,
        model=resolved_model,
        usage_limits=usage_limits,
    )

    num_approved = sum(
        1 for a in result.output.assessments if a.approved
    )
    num_rejected = len(result.output.assessments) - num_approved

    log.info(
        "risk_agent.run.complete",
        num_assessments=len(result.output.assessments),
        num_approved=num_approved,
        num_rejected=num_rejected,
        request_tokens=result.usage().request_tokens,
        response_tokens=result.usage().response_tokens,
    )

    return result.output, result.usage(), result.all_messages()
