"""LangGraph StateGraph pipeline orchestrating trading agents.

Connects regime_detector -> scanner -> strategist -> risk_manager ->
executor in a StateGraph with conditional routing:
  - After scanner: short-circuits to END if no opportunities found.
  - After risk_manager: routes to executor (below threshold),
    approval_gate (above threshold), or END (nothing approved).

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

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from functools import partial
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
from trading.alerts.config import AutoExecuteThresholds
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
        approval_manager: Phase 8 ApprovalManager for trade approval (optional).
        auto_execute_thresholds: Phase 8 thresholds for auto-execute gating (optional).
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
    approval_manager: Any = None
    auto_execute_thresholds: AutoExecuteThresholds | None = None


# ---------------------------------------------------------------------------
# Threshold check
# ---------------------------------------------------------------------------


def _exceeds_threshold(
    assessment: dict,
    trade_proposals: list[dict],
    thresholds: AutoExecuteThresholds,
) -> bool:
    """Check if a risk-approved assessment exceeds auto-execute thresholds.

    Finds the matching trade proposal for the assessment and checks whether
    any of max_loss, delta_impact, or vega_impact exceeds the configured
    thresholds. Returns True (require approval) as the safe default when
    the matching proposal cannot be found.

    Args:
        assessment: A risk assessment dict with ``proposal_id`` and symbol.
        trade_proposals: List of trade proposal dicts from the strategist.
        thresholds: Auto-execute threshold limits.

    Returns:
        True if any threshold is exceeded (needs approval), False otherwise.
    """
    # Find matching proposal by proposal_id or symbol
    proposal_id = assessment.get("proposal_id", "")
    symbol = assessment.get("symbol", "")
    proposal: dict | None = None

    for p in trade_proposals:
        if proposal_id and p.get("proposal_id") == proposal_id:
            proposal = p
            break
        if symbol and p.get("symbol") == symbol:
            proposal = p
            break

    if proposal is None:
        # Safe default: require approval if we cannot find the proposal
        return True

    if abs(proposal.get("max_loss", 0)) > thresholds.max_loss_dollars:
        return True
    if (
        abs(proposal.get("delta_impact", proposal.get("delta", 0)))
        > thresholds.max_delta_impact
    ):
        return True
    if (
        abs(proposal.get("vega_impact", proposal.get("vega", 0)))
        > thresholds.max_vega_impact
    ):
        return True

    return False


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
            data = await deps.redis_client.hgetall(f"mktdata:latest:quote:{symbol}")
            if data:
                price_data[symbol] = data

        input_summary = f"{len(state['watchlist'])} symbols"

        t0 = time.monotonic()
        classification = await deps.regime_detector.detect(iv_batch, price_data)
        duration_ms = (time.monotonic() - t0) * 1000

        await log_agent_decision(
            session_factory=deps.session_factory,
            run_id=run_id,
            agent_name="regime_detector",
            output=classification,
            duration_ms=duration_ms,
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
    """Run the risk manager agent and return assessments.

    Also publishes ``alerts:risk_breach`` to Redis when proposals are
    rejected for risk violations.
    """
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

        # Publish risk breach alerts for rejected proposals
        if deps.redis_client:
            for a in output.assessments:
                if not a.approved:
                    try:
                        await deps.redis_client.publish(
                            "alerts:risk_breach",
                            json.dumps({
                                "symbol": getattr(a, "symbol", ""),
                                "violations": getattr(a, "violations", []),
                                "reason": getattr(a, "reason", str(a)),
                                "run_id": run_id,
                            }),
                        )
                    except Exception:
                        log.warning(
                            "pipeline.risk_node.alert_publish_failed",
                            exc_info=True,
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
    """Run the executor agent and return execution results.

    Publishes ``alerts:trade_executed`` for successful executions and
    ``alerts:trade_rejected`` for failures to Redis for alert routing.
    """
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

        # Publish alert events for each execution result
        if deps.redis_client:
            for r in output.results:
                try:
                    if r.status == "submitted":
                        await deps.redis_client.publish(
                            "alerts:trade_executed",
                            json.dumps({
                                "symbol": r.proposal_id,
                                "status": r.status,
                                "order_id": r.order_id,
                                "details": r.details,
                                "run_id": run_id,
                            }),
                        )
                    else:
                        await deps.redis_client.publish(
                            "alerts:trade_rejected",
                            json.dumps({
                                "symbol": r.proposal_id,
                                "reason": r.details,
                                "status": r.status,
                                "run_id": run_id,
                            }),
                        )
                except Exception:
                    log.warning(
                        "pipeline.executor_node.alert_publish_failed",
                        exc_info=True,
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


async def _approval_gate_node(
    state: PipelineState, deps: PipelineDeps
) -> dict:
    """Route above-threshold trades through human approval.

    Returns immediately with ``pending_approval`` status and spawns a
    background task that waits for approval resolution. If approved,
    the background task invokes ``_executor_node`` directly.

    When ``deps.approval_manager`` is None (fallback), auto-approves
    the trade with a warning log.
    """
    run_id = state.get("run_id", "")
    approval_id = f"approval-{run_id or uuid.uuid4().hex[:8]}"

    # Build context from approved assessments and trade proposals
    approved = [
        a for a in state.get("risk_assessments", []) if a.get("approved")
    ]
    symbols = list({a.get("symbol", "") for a in approved if a.get("symbol")})
    proposals = state.get("trade_proposals", [])

    # Aggregate context from proposals
    total_max_loss = 0.0
    total_max_profit = 0.0
    total_delta = 0.0
    total_theta = 0.0
    total_vega = 0.0
    strategy_types: list[str] = []

    for p in proposals:
        total_max_loss += abs(p.get("max_loss", 0))
        total_max_profit += abs(p.get("max_profit", 0))
        total_delta += abs(p.get("delta_impact", p.get("delta", 0)))
        total_theta += abs(p.get("theta_impact", p.get("theta", 0)))
        total_vega += abs(p.get("vega_impact", p.get("vega", 0)))
        if p.get("strategy_type"):
            strategy_types.append(p["strategy_type"])

    context = {
        "symbols": symbols,
        "strategy_types": strategy_types,
        "max_loss": total_max_loss,
        "max_profit": total_max_profit,
        "delta_impact": total_delta,
        "theta_impact": total_theta,
        "vega_impact": total_vega,
        "timeout_minutes": (
            deps.auto_execute_thresholds.approval_timeout_seconds // 60
            if deps.auto_execute_thresholds
            else 5
        ),
        "run_id": run_id,
    }

    if deps.approval_manager is None:
        log.warning(
            "pipeline.approval_gate.no_manager",
            approval_id=approval_id,
        )
        return {"approval_status": "approved", "approval_id": ""}

    # Spawn background task for approval resolution + execution
    asyncio.create_task(
        _await_approval_and_execute(approval_id, context, state, deps)
    )

    log.info(
        "pipeline.approval_gate.pending",
        approval_id=approval_id,
        symbols=symbols,
    )

    return {"approval_status": "pending_approval", "approval_id": approval_id}


async def _await_approval_and_execute(
    approval_id: str,
    context: dict,
    state: PipelineState,
    deps: PipelineDeps,
) -> None:
    """Background task: wait for approval and execute if granted.

    Calls ``ApprovalManager.request_approval`` which blocks until
    approved, rejected, or timed out. On approval, invokes
    ``_executor_node`` directly. On rejection/timeout, publishes
    ``alerts:trade_rejected`` and returns.

    Wrapped in try/except so errors never crash the background task.
    """
    try:
        result = await deps.approval_manager.request_approval(
            approval_id, context
        )

        if result == "approved":
            log.info(
                "approval.granted",
                approval_id=approval_id,
            )
            # Execute directly -- _executor_node publishes alerts:trade_executed
            await _executor_node(state, deps)

        elif result in ("rejected", "timed_out"):
            log.info(
                f"approval.{result}",
                approval_id=approval_id,
            )
            if deps.redis_client:
                try:
                    await deps.redis_client.publish(
                        "alerts:trade_rejected",
                        json.dumps({
                            "approval_id": approval_id,
                            "reason": result,
                            "symbols": context.get("symbols", []),
                            "run_id": context.get("run_id", ""),
                        }),
                    )
                except Exception:
                    log.warning(
                        "approval.alert_publish_failed",
                        exc_info=True,
                    )

    except Exception as exc:
        log.warning(
            "approval.background_task_error",
            approval_id=approval_id,
            error=str(exc),
            exc_info=True,
        )
        if deps.redis_client:
            try:
                await deps.redis_client.publish(
                    "alerts:system_error",
                    json.dumps({
                        "component": "approval_background_task",
                        "error": str(exc),
                        "approval_id": approval_id,
                    }),
                )
            except Exception:
                pass


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


def _make_route_after_risk(deps: PipelineDeps):
    """Create a three-way routing function after risk_manager.

    Returns a closure that captures ``deps`` for threshold checking.
    Routes to:
      - ``END``: No approved assessments.
      - ``"executor"``: Below threshold or no approval gate configured.
      - ``"approval_gate"``: Above threshold, needs human approval.
    """

    def _route(state: PipelineState) -> str:
        approved = [
            a
            for a in state.get("risk_assessments", [])
            if a.get("approved", False)
        ]
        if not approved:
            log.info(
                "pipeline.route.risk_none_approved", reason="no approvals"
            )
            return END

        # Backward compatible: no approval gate if not configured
        if (
            deps.auto_execute_thresholds is None
            or deps.approval_manager is None
        ):
            return "executor"

        # Check each approved assessment against thresholds
        trade_proposals = state.get("trade_proposals", [])
        for assessment in approved:
            if _exceeds_threshold(
                assessment, trade_proposals, deps.auto_execute_thresholds
            ):
                log.info(
                    "pipeline.route.approval_required",
                    reason="above auto-execute threshold",
                )
                return "approval_gate"

        return "executor"

    return _route


# Keep module-level reference for backward compatibility (tests may import it)
def route_after_risk(state: PipelineState) -> str:
    """Route to executor if any proposals approved, else END.

    Short-circuits before execution when the risk gate rejects
    every proposal -- nothing to execute.

    Note: This is the legacy two-way router. The pipeline uses
    ``_make_route_after_risk(deps)`` for the three-way version.
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

    The graph has 5-6 nodes (regime_detector, scanner, strategist,
    risk_manager, executor, and optionally approval_gate) connected
    by edges with conditional routing that allows early termination
    and human approval gating for above-threshold trades.

    Graph topology::

        START -> regime_detector -> scanner -> [conditional] -> strategist
                                      |                             |
                                      +-> END (no opps)      risk_manager
                                                                    |
                                                            [conditional]
                                                           /      |       \\
                                                  executor   approval_gate  END
                                                      |          |
                                                     END        END
                                                          (bg task handles)

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
    workflow.add_node(
        "approval_gate", lambda state: _approval_gate_node(state, deps)
    )

    # Edges: START -> regime_detector -> scanner
    workflow.add_edge(START, "regime_detector")
    workflow.add_edge("regime_detector", "scanner")

    # Conditional: scanner -> strategist or END
    workflow.add_conditional_edges("scanner", route_after_scan)

    # Linear: strategist -> risk_manager
    workflow.add_edge("strategist", "risk_manager")

    # Conditional: risk_manager -> executor, approval_gate, or END
    workflow.add_conditional_edges(
        "risk_manager",
        _make_route_after_risk(deps),
    )

    # Terminal edges
    workflow.add_edge("executor", END)
    workflow.add_edge("approval_gate", END)

    # Compile (with optional checkpoint persistence)
    graph = workflow.compile(checkpointer=checkpointer)

    log.info(
        "pipeline.created",
        nodes=[
            "regime_detector",
            "scanner",
            "strategist",
            "risk_manager",
            "executor",
            "approval_gate",
        ],
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
        "approval_status": "",
        "approval_id": "",
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
        approval_status=final_state.get("approval_status", ""),
    )

    return final_state
