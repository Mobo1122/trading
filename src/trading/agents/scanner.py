"""Scanner PydanticAI agent for identifying options trading opportunities.

The scanner is the pipeline entry point. It scans watchlist symbols using
IV analytics, earnings calendar, and market data tools to identify
opportunities worth passing to the strategist agent.

Each tool wraps a real service interface (IVEngine, EarningsCalendar, Redis)
with error handling that returns JSON error messages instead of raising
exceptions -- the LLM can interpret errors and continue scanning.

Exports:
    scanner_agent: PydanticAI Agent instance with registered tools.
    ScannerDeps: Dataclass for dependency injection into tools.
    run_scanner: Async helper that runs the scanner with usage limits.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import structlog
from pydantic_ai import Agent, ModelSettings, RunContext, UsageLimits
from pydantic_ai.usage import Usage

from trading.agents.models import ScannerOutput
from trading.analytics.earnings import EarningsCalendar
from trading.analytics.iv_engine import IVEngine
from trading.config import Settings

log = structlog.get_logger("trading.agents.scanner")


# ---------------------------------------------------------------------------
# Dependency injection container
# ---------------------------------------------------------------------------


@dataclass
class ScannerDeps:
    """Dependencies injected into scanner agent tools.

    Attributes:
        iv_engine: IV rank/percentile computation engine.
        earnings_calendar: Finnhub-backed earnings calendar service.
        redis_client: Async Redis client for latest market data lookup
            via ``HGET market_data:{symbol}``.
        watchlist: List of ticker symbols to scan.
        settings: Application settings for agent configuration.
    """

    iv_engine: IVEngine
    earnings_calendar: EarningsCalendar
    redis_client: Any
    watchlist: list[str]
    settings: Settings


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------

scanner_agent = Agent(
    model=None,  # Set at runtime from config in run_scanner
    output_type=ScannerOutput,
    deps_type=ScannerDeps,
    instructions=(
        "You are a trading opportunity scanner for an options trading system. "
        "Your job is to evaluate each symbol in the watchlist and identify "
        "potential trading opportunities based on IV analytics, earnings "
        "proximity, and current market data.\n\n"
        "For each symbol:\n"
        "1. Check IV data (rank, percentile) -- high IV rank suggests "
        "premium-selling opportunities, low IV rank suggests buying.\n"
        "2. Check earnings proximity -- earnings within 7 days means elevated "
        "IV (potential crush play) or avoid (if risk is too high).\n"
        "3. Check market snapshot -- current price, volume, and recent movement "
        "provide trade context.\n\n"
        "Return opportunities ranked by confidence. Only flag symbols with a "
        "clear signal; do not force opportunities where none exist. "
        "Explain your reasoning for each flagged opportunity and for the "
        "overall scan summary."
    ),
    model_settings=ModelSettings(temperature=0.1, max_tokens=2000),
)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@scanner_agent.tool
async def get_iv_data(ctx: RunContext[ScannerDeps], symbol: str) -> str:
    """Get IV rank and percentile analytics for a symbol.

    Returns JSON with current_iv, iv_rank (0-100), iv_percentile (0-100),
    52-week high/low IV, and the number of historical data points used.
    """
    try:
        iv_data = await ctx.deps.iv_engine.compute(symbol)
        return iv_data.model_dump_json()
    except Exception as exc:
        log.warning("tool.get_iv_data.error", symbol=symbol, error=str(exc))
        return json.dumps({"error": str(exc), "symbol": symbol})


@scanner_agent.tool
async def get_earnings_info(ctx: RunContext[ScannerDeps], symbol: str) -> str:
    """Get upcoming earnings information for a symbol.

    Returns JSON with earnings_date, days_until, hour (bmo/amc),
    eps_estimate, and revenue_estimate. Returns null if no earnings
    are within the lookout window.
    """
    try:
        flag = await ctx.deps.earnings_calendar.get_earnings_flag(symbol)
        if flag is None:
            return json.dumps(
                {"symbol": symbol, "earnings_upcoming": False}
            )
        return flag.model_dump_json()
    except Exception as exc:
        log.warning(
            "tool.get_earnings_info.error", symbol=symbol, error=str(exc)
        )
        return json.dumps({"error": str(exc), "symbol": symbol})


@scanner_agent.tool
async def get_market_snapshot(ctx: RunContext[ScannerDeps], symbol: str) -> str:
    """Get the latest market data snapshot for a symbol from Redis.

    Returns JSON with bid, ask, last price, volume, implied volatility,
    and other quote fields. Returns an error message if no data is cached.
    """
    try:
        data = await ctx.deps.redis_client.hgetall(f"market_data:{symbol}")
        if not data:
            return json.dumps(
                {"symbol": symbol, "error": "No market data available"}
            )
        # Include symbol for clarity
        data["symbol"] = symbol
        return json.dumps(data)
    except Exception as exc:
        log.warning(
            "tool.get_market_snapshot.error", symbol=symbol, error=str(exc)
        )
        return json.dumps({"error": str(exc), "symbol": symbol})


@scanner_agent.tool
async def get_watchlist(ctx: RunContext[ScannerDeps]) -> str:
    """Get the list of symbols to scan.

    Returns JSON array of ticker symbols from the configured watchlist.
    """
    return json.dumps(ctx.deps.watchlist)


# ---------------------------------------------------------------------------
# Run helper
# ---------------------------------------------------------------------------


async def run_scanner(
    deps: ScannerDeps,
    model: str | None = None,
    usage_limits: UsageLimits | None = None,
    prompt_prefix: str = "",
) -> tuple[ScannerOutput, Usage, list]:
    """Run the scanner agent with usage limits and structured output.

    Args:
        deps: Dependency container with IV engine, earnings calendar,
            Redis client, watchlist, and settings.
        model: PydanticAI model string override. If None, uses the
            scanner-specific model from agent config (or default model).
        usage_limits: Token/request limits. Defaults to
            ``UsageLimits(request_limit=10, response_tokens_limit=4000)``.
        prompt_prefix: Optional text prepended to the scanner prompt,
            typically regime context from the regime detector node.

    Returns:
        Tuple of (ScannerOutput, Usage, all_messages) where:
        - ScannerOutput: Validated structured output with opportunities.
        - Usage: Token usage statistics for the run.
        - all_messages: Full message history for audit logging.
    """
    agent_config = deps.settings.agents
    resolved_model = model or agent_config.get_model("scanner")

    if usage_limits is None:
        usage_limits = UsageLimits(
            request_limit=agent_config.request_limit,
            response_tokens_limit=agent_config.response_tokens_limit,
        )

    prompt = (
        f"{prompt_prefix}"
        f"Scan the following watchlist for trading opportunities: "
        f"{', '.join(deps.watchlist)}. "
        f"Use your tools to gather IV data, earnings info, and market "
        f"snapshots for each symbol, then identify the best opportunities."
    )

    log.info(
        "scanner.run.start",
        watchlist=deps.watchlist,
        model=resolved_model,
        request_limit=usage_limits.request_limit,
    )

    result = await scanner_agent.run(
        prompt,
        deps=deps,
        model=resolved_model,
        usage_limits=usage_limits,
    )

    log.info(
        "scanner.run.complete",
        num_opportunities=len(result.output.opportunities),
        symbols_scanned=result.output.symbols_scanned,
        request_tokens=result.usage().request_tokens,
        response_tokens=result.usage().response_tokens,
    )

    return result.output, result.usage(), result.all_messages()
