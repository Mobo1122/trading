"""Executor PydanticAI agent wrapping OrderExecutionService.

The executor is the final pipeline stage. It takes risk-approved trade
proposals and submits them to IB via the Phase 4 OrderExecutionService.

Double risk-gate protection: submit_trade calls execution_service.submit_order(),
which internally calls evaluate_with_failsafe() again. Even if the LLM agent
misbehaves, the deterministic risk gate is non-bypassable.

The executor never modifies trade parameters -- it executes exactly what
was approved by the risk manager.

Exports:
    executor_agent: PydanticAI Agent instance with registered tools.
    ExecutorDeps: Dataclass for dependency injection into tools.
    run_executor: Async helper that runs the executor with usage limits.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import structlog
from pydantic_ai import Agent, ModelSettings, RunContext, UsageLimits
from pydantic_ai.usage import Usage

from trading.agents.models import ExecutorOutput
from trading.config import Settings
from trading.orders.execution_service import OrderExecutionService
from trading.risk.models import GreeksImpact, TradeLeg, TradeProposal

log = structlog.get_logger("trading.agents.executor_agent")


# ---------------------------------------------------------------------------
# Dependency injection container
# ---------------------------------------------------------------------------


@dataclass
class ExecutorDeps:
    """Dependencies injected into executor agent tools.

    Attributes:
        execution_service: Phase 4 OrderExecutionService for risk-gated
            order submission via IB.
        session_factory: SQLAlchemy async session factory for DB access.
        approved_assessments: Risk-approved assessments from pipeline state.
        trade_proposals: Original strategist proposals for cross-reference.
        settings: Application settings for agent configuration.
    """

    execution_service: OrderExecutionService
    session_factory: Any
    approved_assessments: list[dict] = field(default_factory=list)
    trade_proposals: list[dict] = field(default_factory=list)
    settings: Settings = field(default_factory=Settings)


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------

executor_agent = Agent(
    model=None,  # Set at runtime from config in run_executor
    output_type=ExecutorOutput,
    deps_type=ExecutorDeps,
    instructions=(
        "You are an options trade executor. For each risk-approved trade "
        "proposal:\n"
        "1. Use the submit_trade tool to place the order via IB\n"
        "2. Record the result (order_id, status, any errors)\n"
        "3. If submission fails, log the error but continue with "
        "remaining trades\n"
        "You are the final stage -- only execute trades that have been "
        "explicitly approved by the risk manager. Do not modify trade "
        "parameters."
    ),
    model_settings=ModelSettings(temperature=0.0, max_tokens=1500),
)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@executor_agent.tool
async def submit_trade(
    ctx: RunContext[ExecutorDeps],
    proposal_json: str,
) -> str:
    """Submit a risk-approved trade to IB via OrderExecutionService.

    Constructs a TradeProposal and delegates to execution_service.submit_order(),
    which internally runs evaluate_with_failsafe() as a double-check that the
    deterministic risk gate is non-bypassable.
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

        # Construct TradeProposal for the execution service
        trade_proposal = TradeProposal(
            legs=legs,
            estimated_greeks=GreeksImpact(
                delta=proposal_data.get("estimated_delta", 0.0),
                gamma=proposal_data.get("estimated_gamma", 0.0),
                theta=proposal_data.get("estimated_theta", 0.0),
                vega=proposal_data.get("estimated_vega", 0.0),
            ),
            max_loss=proposal_data.get("max_loss", 0.0),
            strategy_type=proposal_data.get("strategy_type", "unknown"),
            account_value=proposal_data.get("account_value", 100000.0),
        )

        # Submit via execution service (has its own risk gate)
        decision, trade = await ctx.deps.execution_service.submit_order(
            trade_proposal
        )

        if not decision.approved:
            log.warning(
                "executor.trade_rejected_by_risk_gate",
                proposal_symbol=proposal_data.get("symbol", "unknown"),
                violated_rule=(
                    decision.violated_rule.value
                    if decision.violated_rule
                    else None
                ),
            )
            return json.dumps({
                "status": "rejected",
                "order_id": None,
                "details": (
                    f"Rejected by execution risk gate: "
                    f"{decision.violated_rule.value if decision.violated_rule else 'unknown'} "
                    f"- {decision.details}"
                ),
            })

        order_id = None
        if trade is not None:
            order_id = str(trade.order.orderId)

        log.info(
            "executor.trade_submitted",
            proposal_symbol=proposal_data.get("symbol", "unknown"),
            order_id=order_id,
        )

        return json.dumps({
            "status": "submitted",
            "order_id": order_id,
            "details": f"Order placed for {proposal_data.get('symbol', 'unknown')}",
        })

    except Exception as exc:
        log.warning(
            "executor.submit_trade_failed",
            error=str(exc),
            exc_info=True,
        )
        return json.dumps({
            "status": "failed",
            "order_id": None,
            "details": f"Submission failed: {exc}",
        })


@executor_agent.tool
async def get_approved_trades(ctx: RunContext[ExecutorDeps]) -> str:
    """Get the list of risk-approved trades to execute.

    Returns JSON array of approved assessments cross-referenced with
    the original trade proposals. Only includes proposals where the
    risk assessment approved=True.
    """
    approved = []
    for assessment in ctx.deps.approved_assessments:
        if not assessment.get("approved", False):
            continue

        # Cross-reference with original proposal by proposal_id
        proposal_id = assessment.get("proposal_id", "")
        matching_proposal = None
        for p in ctx.deps.trade_proposals:
            # Proposals may have symbol as identifier
            if p.get("proposal_id") == proposal_id:
                matching_proposal = p
                break

        approved.append({
            "assessment": assessment,
            "proposal": matching_proposal,
        })

    return json.dumps(approved)


# ---------------------------------------------------------------------------
# Run helper
# ---------------------------------------------------------------------------


async def run_executor(
    deps: ExecutorDeps,
    model: str | None = None,
    usage_limits: UsageLimits | None = None,
) -> tuple[ExecutorOutput, Usage, list]:
    """Run the executor agent with usage limits and structured output.

    Args:
        deps: Dependency container with execution service, approved
            assessments, trade proposals, and settings.
        model: PydanticAI model string override. If None, uses the
            executor-specific model from agent config (or default model).
        usage_limits: Token/request limits. Defaults to
            ``UsageLimits(request_limit=10, response_tokens_limit=2000)``.

    Returns:
        Tuple of (ExecutorOutput, Usage, all_messages) where:
        - ExecutorOutput: Validated structured output with execution results.
        - Usage: Token usage statistics for the run.
        - all_messages: Full message history for audit logging.
    """
    agent_config = deps.settings.agents
    resolved_model = model or agent_config.get_model("executor")

    if usage_limits is None:
        usage_limits = UsageLimits(
            request_limit=agent_config.request_limit,
            response_tokens_limit=min(
                agent_config.response_tokens_limit, 2000
            ),
        )

    # Build a summary of approved trades for the prompt
    approved_summaries = []
    for i, a in enumerate(deps.approved_assessments):
        if a.get("approved", False):
            pid = a.get("proposal_id", "unknown")
            approved_summaries.append(f"  {i + 1}. Proposal {pid}")

    summary = (
        "\n".join(approved_summaries)
        if approved_summaries
        else "No approved trades"
    )

    prompt = (
        f"Execute the following approved trades:\n{summary}\n\n"
        f"Submit each trade and report results."
    )

    log.info(
        "executor.run.start",
        num_approved=len(approved_summaries),
        model=resolved_model,
        request_limit=usage_limits.request_limit,
    )

    result = await executor_agent.run(
        prompt,
        deps=deps,
        model=resolved_model,
        usage_limits=usage_limits,
    )

    num_submitted = sum(
        1 for r in result.output.results if r.status == "submitted"
    )
    num_failed = sum(
        1 for r in result.output.results if r.status == "failed"
    )

    log.info(
        "executor.run.complete",
        num_results=len(result.output.results),
        num_submitted=num_submitted,
        num_failed=num_failed,
        request_tokens=result.usage().request_tokens,
        response_tokens=result.usage().response_tokens,
    )

    return result.output, result.usage(), result.all_messages()
