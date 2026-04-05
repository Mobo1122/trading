"""LangGraph StateGraph pipeline orchestrating trading agents.

Connects regime_detector -> scanner -> strategist -> risk_manager ->
executor in a StateGraph with conditional routing:
  - After scanner: short-circuits to END if no opportunities found.
  - After risk_manager: short-circuits to END if nothing approved.

The regime_detector node runs first to classify market conditions and
inject regime context into scanner prompts. Rolling candidates from
ExpirationMonitor are passed in via ``run_pipeline()`` by the caller.

Each node function wraps its PydanticAI agent run, translates between
PipelineState (TypedDict with ``list[dict]``) and the agent's typed
deps/output, and handles errors gracefully (partial state, never crash).

Exports:
    PipelineDeps: Dataclass of all dependencies needed by the pipeline.
    create_pipeline: Factory that builds and compiles the StateGraph.
    run_pipeline: Convenience async runner with logging and run_id.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from trading.agents.config import AgentConfig
from trading.agents.executor_agent import ExecutorDeps, run_executor
from trading.agents.logging import log_agent_decision
from trading.agents.regime import (
    REGIME_STRATEGY_WEIGHTS,
    MarketRegime,
    RegimeClassification,
    RegimeDetector,
)
from trading.agents.risk_agent import RiskAgentDeps, run_risk_agent
from trading.agents.rolling import ExpirationMonitor
from trading.agents.scanner import ScannerDeps, run_scanner
from trading.agents.state import PipelineState
from trading.agents.strategist import StrategistDeps, run_strategist
from trading.config import Settings

log = structlog.get_logger("trading.agents.pipeline")


# ---------------------------------------------------------------------------
# Dependency container
# ---------------------------------------------------------------------------


@dataclass
class PipelineDeps:
    """All dependencies needed by pipeline node functions.

    Aggregates the dependencies for every agent into a single container
    that is bound to node closures at graph-build time.

    Attributes:
        iv_engine: Phase 2 IV rank/percentile engine.
        earnings_calendar: Phase 2 Finnhub earnings calendar service.
        contract_resolver: Phase 1 ContractResolver for option chains.
        risk_manager: Phase 3 deterministic risk engine.
        execution_service: Phase 4 OrderExecutionService for IB orders.
        redis_client: Async Redis client (decode_responses=True).
        session_factory: SQLAlchemy async session factory.
        settings: Application settings (includes AgentConfig).
        account_value: Current account value in dollars for sizing.
        regime_detector: Phase 6 regime detection module (optional).
        expiration_monitor: Phase 6 expiration monitor for rolling (optional).
    """

    iv_engine: Any
    earnings_calendar: Any
    contract_resolver: Any
    risk_manager: Any
    execution_service: Any
    redis_client: Any
    session_factory: Any
    settings: Settings
    account_value: float = 100_000.0
    regime_detector: Any = None
    expiration_monitor: Any = None


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------


async def _regime_node(state: PipelineState, deps: PipelineDeps) -> dict:
    """Run regime detection and return classification for downstream nodes.

    Non-fatal: if regime detection is unavailable or errors, returns an
    empty classification dict so the scanner runs without regime context.
    """
    run_id = state.get("run_id", "")

    try:
        if deps.regime_detector is None:
            return {"regime_classification": {}}

        # Compute IV batch for watchlist
        iv_batch = await deps.iv_engine.compute_batch(state["watchlist"])

        # Gather latest price data from Redis
        price_data: dict[str, dict] = {}
        for symbol in state["watchlist"]:
            data = await deps.redis_client.hgetall(f"market_data:{symbol}")
            if data:
                price_data[symbol] = data

        input_summary = f"{len(state['watchlist'])} symbols"

        classification = await deps.regime_detector.detect(iv_batch, price_data)
        t0 = time.monotonic()

        await log_agent_decision(
            session_factory=deps.session_factory,
            run_id=run_id,
            agent_name="regime_detector",
            output=classification,
            duration_ms=0,
            input_summary=input_summary,
        )

        log.info(
            "pipeline.regime_node.complete",
            regime=classification.regime.value,
            confidence=classification.confidence,
        )

        return {"regime_classification": classification.model_dump()}

    except Exception as exc:
        log.error("pipeline.regime_node.error", error=str(exc), exc_info=True)
        return {"regime_classification": {}}


async def _scan_node(state: PipelineState, deps: PipelineDeps) -> dict:
    """Run the scanner agent and return opportunities.

    If the scanner errors out, the node returns an empty opportunities
    list and records the abort reason so the routing function can
    short-circuit the pipeline.
    """
    run_id = state.get("run_id", "")
    input_summary = f"{len(state['watchlist'])} symbols: {', '.join(state['watchlist'][:5])}"
    t0 = time.monotonic()

    try:
        # Build regime context string for scanner prompt
        regime_context = ""
        regime_data = state.get("regime_classification", {})
        if (
            regime_data
            and regime_data.get("regime")
            and regime_data.get("regime") != "unknown"
        ):
            regime_name = regime_data["regime"]
            try:
                weights = REGIME_STRATEGY_WEIGHTS.get(
                    MarketRegime(regime_name), {}
                )
            except ValueError:
                weights = {}
            regime_context = (
                f"CURRENT MARKET REGIME: {regime_name}\n"
                f"Regime confidence: {regime_data.get('confidence', 0):.0%}\n"
                f"Trend: {regime_data.get('trend_signal', 'unknown')}, "
                f"Volatility: {regime_data.get('volatility_signal', 'unknown')}\n"
                f"Preferred strategy mix: {weights}\n"
                f"Adapt your opportunity scanning to favor strategies that "
                f"perform well in this regime.\n\n"
            )

        scanner_deps = ScannerDeps(
            iv_engine=deps.iv_engine,
            earnings_calendar=deps.earnings_calendar,
            redis_client=deps.redis_client,
            watchlist=state["watchlist"],
            settings=deps.settings,
        )

        output, usage, messages = await run_scanner(
            scanner_deps, prompt_prefix=regime_context
        )
        duration_ms = int((time.monotonic() - t0) * 1000)

        log.info(
            "pipeline.scan_node.complete",
            num_opportunities=len(output.opportunities),
            symbols_scanned=output.symbols_scanned,
            request_tokens=usage.request_tokens,
            response_tokens=usage.response_tokens,
        )

        await log_agent_decision(
            session_factory=deps.session_factory,
            run_id=run_id,
            agent_name="scanner",
            output=output,
            messages=messages,
            usage=usage,
            duration_ms=duration_ms,
            input_summary=input_summary,
        )

        return {
            "opportunities": [opp.model_dump() for opp in output.opportunities],
            "scanner_reasoning": output.reasoning,
        }

    except Exception as exc:
        duration_ms = int((time.monotonic() - t0) * 1000)
        log.error("pipeline.scan_node.error", error=str(exc), exc_info=True)

        await log_agent_decision(
            session_factory=deps.session_factory,
            run_id=run_id,
            agent_name="scanner",
            error=str(exc),
            duration_ms=duration_ms,
            input_summary=input_summary,
        )

        return {
            "opportunities": [],
            "scanner_reasoning": f"Scanner failed: {exc}",
            "aborted_at": "scanner",
        }


async def _strategist_node(state: PipelineState, deps: PipelineDeps) -> dict:
    """Run the strategist agent and return trade proposals."""
    run_id = state.get("run_id", "")
    input_summary = f"{len(state['opportunities'])} opportunities from scanner"
    t0 = time.monotonic()

    try:
        risk_profile = (
            deps.settings.risk_limits.paper
            if deps.settings.trading.mode == "paper"
            else deps.settings.risk_limits.live
        )

        strategist_deps = StrategistDeps(
            contract_resolver=deps.contract_resolver,
            iv_engine=deps.iv_engine,
            redis_client=deps.redis_client,
            risk_limits=risk_profile,
            account_value=deps.account_value,
            opportunities=state["opportunities"],
            settings=deps.settings,
        )

        output, usage, messages = await run_strategist(strategist_deps)
        duration_ms = int((time.monotonic() - t0) * 1000)

        log.info(
            "pipeline.strategist_node.complete",
            num_proposals=len(output.proposals),
            request_tokens=usage.request_tokens,
            response_tokens=usage.response_tokens,
        )

        await log_agent_decision(
            session_factory=deps.session_factory,
            run_id=run_id,
            agent_name="strategist",
            output=output,
            messages=messages,
            usage=usage,
            duration_ms=duration_ms,
            input_summary=input_summary,
        )

        return {
            "trade_proposals": [p.model_dump() for p in output.proposals],
            "strategist_reasoning": output.reasoning,
        }

    except Exception as exc:
        duration_ms = int((time.monotonic() - t0) * 1000)
        log.error(
            "pipeline.strategist_node.error", error=str(exc), exc_info=True
        )

        await log_agent_decision(
            session_factory=deps.session_factory,
            run_id=run_id,
            agent_name="strategist",
            error=str(exc),
            duration_ms=duration_ms,
            input_summary=input_summary,
        )

        return {
            "trade_proposals": [],
            "strategist_reasoning": f"Strategist failed: {exc}",
            "aborted_at": "strategist",
        }


async def _risk_node(state: PipelineState, deps: PipelineDeps) -> dict:
    """Run the risk manager agent and return assessments."""
    run_id = state.get("run_id", "")
    input_summary = f"{len(state['trade_proposals'])} trade proposals from strategist"
    t0 = time.monotonic()

    try:
        risk_deps = RiskAgentDeps(
            risk_manager=deps.risk_manager,
            redis_client=deps.redis_client,
            session_factory=deps.session_factory,
            trade_proposals=state["trade_proposals"],
            settings=deps.settings,
        )

        output, usage, messages = await run_risk_agent(risk_deps)
        duration_ms = int((time.monotonic() - t0) * 1000)

        log.info(
            "pipeline.risk_node.complete",
            num_assessments=len(output.assessments),
            num_approved=sum(1 for a in output.assessments if a.approved),
            request_tokens=usage.request_tokens,
            response_tokens=usage.response_tokens,
        )

        await log_agent_decision(
            session_factory=deps.session_factory,
            run_id=run_id,
            agent_name="risk_manager",
            output=output,
            messages=messages,
            usage=usage,
            duration_ms=duration_ms,
            input_summary=input_summary,
        )

        return {
            "risk_assessments": [a.model_dump() for a in output.assessments],
            "risk_reasoning": output.reasoning,
        }

    except Exception as exc:
        duration_ms = int((time.monotonic() - t0) * 1000)
        log.error("pipeline.risk_node.error", error=str(exc), exc_info=True)

        await log_agent_decision(
            session_factory=deps.session_factory,
            run_id=run_id,
            agent_name="risk_manager",
            error=str(exc),
            duration_ms=duration_ms,
            input_summary=input_summary,
        )

        return {
            "risk_assessments": [],
            "risk_reasoning": f"Risk agent failed: {exc}",
            "aborted_at": "risk_manager",
        }


async def _executor_node(state: PipelineState, deps: PipelineDeps) -> dict:
    """Run the executor agent and return execution results."""
    run_id = state.get("run_id", "")
    approved = [
        a for a in state["risk_assessments"] if a.get("approved", False)
    ]
    input_summary = f"{len(approved)} approved proposals for execution"
    t0 = time.monotonic()

    try:
        executor_deps = ExecutorDeps(
            execution_service=deps.execution_service,
            session_factory=deps.session_factory,
            approved_assessments=approved,
            trade_proposals=state["trade_proposals"],
            settings=deps.settings,
            run_id=state.get("run_id", ""),
        )

        output, usage, messages = await run_executor(executor_deps)
        duration_ms = int((time.monotonic() - t0) * 1000)

        log.info(
            "pipeline.executor_node.complete",
            num_results=len(output.results),
            num_submitted=sum(
                1 for r in output.results if r.status == "submitted"
            ),
            request_tokens=usage.request_tokens,
            response_tokens=usage.response_tokens,
        )

        await log_agent_decision(
            session_factory=deps.session_factory,
            run_id=run_id,
            agent_name="executor",
            output=output,
            messages=messages,
            usage=usage,
            duration_ms=duration_ms,
            input_summary=input_summary,
        )

        return {
            "execution_results": [r.model_dump() for r in output.results],
            "executor_reasoning": output.reasoning,
        }

    except Exception as exc:
        duration_ms = int((time.monotonic() - t0) * 1000)
        log.error(
            "pipeline.executor_node.error", error=str(exc), exc_info=True
        )

        await log_agent_decision(
            session_factory=deps.session_factory,
            run_id=run_id,
            agent_name="executor",
            error=str(exc),
            duration_ms=duration_ms,
            input_summary=input_summary,
        )

        return {
            "execution_results": [],
            "executor_reasoning": f"Executor failed: {exc}",
            "aborted_at": "executor",
        }


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------


def route_after_scan(state: PipelineState) -> str:
    """Route to strategist if opportunities found, else END.

    Short-circuits the entire pipeline when the scanner finds nothing
    worth trading -- no reason to burn tokens on downstream agents.
    """
    if state.get("opportunities"):
        return "strategist"
    log.info("pipeline.route.scan_empty", reason="no opportunities found")
    return END


def route_after_risk(state: PipelineState) -> str:
    """Route to executor if any proposals approved, else END.

    Short-circuits before execution when the risk gate rejects
    every proposal -- nothing to execute.
    """
    approved = [
        a
        for a in state.get("risk_assessments", [])
        if a.get("approved", False)
    ]
    if approved:
        return "executor"
    log.info("pipeline.route.risk_none_approved", reason="no approvals")
    return END


# ---------------------------------------------------------------------------
# Pipeline factory
# ---------------------------------------------------------------------------


async def create_pipeline(
    deps: PipelineDeps,
    checkpointer: Any | None = None,
) -> CompiledStateGraph:
    """Build and compile the LangGraph StateGraph pipeline.

    The graph has 5 nodes (regime_detector, scanner, strategist,
    risk_manager, executor) connected by edges with two conditional
    routing points that allow early termination when nothing to do.

    Graph topology::

        START -> regime_detector -> scanner -> [conditional] -> strategist
                                      |                             |
                                      +-> END (no opps)      risk_manager
                                                                    |
                                                            [conditional]
                                                                    |
                                                            executor -> END
                                                                |
                                                            END (no approvals)

    Args:
        deps: Pipeline dependencies bound to node closures.
        checkpointer: Optional LangGraph checkpoint saver for state
            persistence (e.g., ``AsyncPostgresSaver``).

    Returns:
        A compiled StateGraph ready for ``await graph.ainvoke(state)``.
    """
    workflow = StateGraph(PipelineState)

    # Add nodes -- bind deps via closure so each node receives them
    workflow.add_node("regime_detector", lambda state: _regime_node(state, deps))
    workflow.add_node("scanner", lambda state: _scan_node(state, deps))
    workflow.add_node("strategist", lambda state: _strategist_node(state, deps))
    workflow.add_node("risk_manager", lambda state: _risk_node(state, deps))
    workflow.add_node("executor", lambda state: _executor_node(state, deps))

    # Edges: START -> regime_detector -> scanner
    workflow.add_edge(START, "regime_detector")
    workflow.add_edge("regime_detector", "scanner")

    # Conditional: scanner -> strategist or END
    workflow.add_conditional_edges("scanner", route_after_scan)

    # Linear: strategist -> risk_manager
    workflow.add_edge("strategist", "risk_manager")

    # Conditional: risk_manager -> executor or END
    workflow.add_conditional_edges("risk_manager", route_after_risk)

    # Linear: executor -> END
    workflow.add_edge("executor", END)

    # Compile (with optional checkpoint persistence)
    graph = workflow.compile(checkpointer=checkpointer)

    log.info(
        "pipeline.created",
        nodes=["regime_detector", "scanner", "strategist", "risk_manager", "executor"],
        has_checkpointer=checkpointer is not None,
    )

    return graph


# ---------------------------------------------------------------------------
# Convenience runner
# ---------------------------------------------------------------------------


async def run_pipeline(
    graph: CompiledStateGraph,
    watchlist: list[str],
    run_id: str | None = None,
    account_value: float = 100_000.0,
    regime_classification: dict | None = None,
    rolling_candidates: list[dict] | None = None,
) -> PipelineState:
    """Run the full agent pipeline for a watchlist.

    Creates an initial state, invokes the compiled graph, and returns
    the final state. Each invocation gets a unique run_id used as the
    LangGraph thread_id for checkpoint isolation.

    Args:
        graph: Compiled StateGraph from ``create_pipeline()``.
        watchlist: Symbols to scan for opportunities.
        run_id: Unique identifier for this run. Auto-generated if None.
        account_value: Current account value for position sizing.
        regime_classification: Optional pre-computed regime classification
            dict to inject into state (bypasses regime_detector node).
        rolling_candidates: Optional pre-scanned rolling candidates from
            ExpirationMonitor to inject into pipeline state.

    Returns:
        The final PipelineState after all nodes (or early termination).
    """
    if run_id is None:
        run_id = str(uuid.uuid4())

    initial_state: PipelineState = {
        "watchlist": watchlist,
        "opportunities": [],
        "trade_proposals": [],
        "risk_assessments": [],
        "execution_results": [],
        "scanner_reasoning": "",
        "strategist_reasoning": "",
        "risk_reasoning": "",
        "executor_reasoning": "",
        "run_id": run_id,
        "aborted_at": "",
        "regime_classification": regime_classification or {},
        "rolling_candidates": rolling_candidates or [],
        "rolling_decisions": [],
    }

    config = {"configurable": {"thread_id": run_id}}

    log.info(
        "pipeline.run.start",
        run_id=run_id,
        watchlist=watchlist,
        num_symbols=len(watchlist),
    )

    final_state: PipelineState = await graph.ainvoke(initial_state, config)

    # Determine completion status
    aborted = final_state.get("aborted_at", "")
    num_opps = len(final_state.get("opportunities", []))
    num_proposals = len(final_state.get("trade_proposals", []))
    num_approved = sum(
        1
        for a in final_state.get("risk_assessments", [])
        if a.get("approved", False)
    )
    num_executed = len(final_state.get("execution_results", []))

    log.info(
        "pipeline.run.complete",
        run_id=run_id,
        aborted_at=aborted or None,
        opportunities=num_opps,
        proposals=num_proposals,
        approved=num_approved,
        executed=num_executed,
    )

    return final_state
