---
phase: 05-core-agent-pipeline
plan: 05
subsystem: agents
tags: [langgraph, stategraph, pipeline-orchestration, conditional-routing, checkpoint, options-trading]

# Dependency graph
requires:
  - phase: 05-02
    provides: "Scanner agent (scanner_agent, ScannerDeps, run_scanner)"
  - phase: 05-03
    provides: "Strategist agent (strategist_agent, StrategistDeps, run_strategist)"
  - phase: 05-04
    provides: "Risk manager agent and executor agent (run_risk_agent, run_executor)"
provides:
  - "LangGraph StateGraph pipeline (create_pipeline, run_pipeline)"
  - "PipelineDeps dataclass aggregating all agent dependencies"
  - "Conditional routing: short-circuit on empty opportunities or zero approvals"
  - "Checkpoint persistence support via optional AsyncPostgresSaver"
affects:
  - phase: 05-06
    reason: "Decision logging hooks into pipeline node functions"
  - phase: 05-07
    reason: "App wiring creates PipelineDeps and calls create_pipeline"
  - phase: 06
    reason: "Advanced agents extend the pipeline graph"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "LangGraph StateGraph with closure-bound deps for node functions"
    - "Conditional edges for early termination (scan empty, risk rejected)"
    - "PydanticAI agent output -> model_dump() -> TypedDict state -> next node"
    - "UUID-based thread_id for checkpoint isolation per pipeline run"

# File tracking
key-files:
  created:
    - src/trading/agents/pipeline.py
  modified: []

# Decisions
decisions:
  - id: "05-05-01"
    decision: "Node functions receive deps via closure binding in create_pipeline factory"
    rationale: "LangGraph node functions take only state as argument; closure capture of PipelineDeps avoids global state"
  - id: "05-05-02"
    decision: "Routing functions use simple list emptiness checks (not length thresholds)"
    rationale: "Even a single opportunity or approval is worth processing; the individual agents handle quality filtering"
  - id: "05-05-03"
    decision: "Error handling in nodes returns partial state instead of raising"
    rationale: "Pipeline must not crash on individual agent failure; aborted_at field records failure point for diagnostics"

# Metrics
duration: "2min"
completed: "2026-04-04"
---

# Phase 5 Plan 5: LangGraph Pipeline Orchestration Summary

LangGraph StateGraph connecting all four agents (scanner, strategist, risk_manager, executor) with two conditional routing points that short-circuit on empty opportunities or zero risk approvals.

## What Was Built

### PipelineDeps Dataclass
Aggregates all dependencies needed by the pipeline's four agents into a single container: iv_engine, earnings_calendar, contract_resolver, risk_manager, execution_service, redis_client, session_factory, settings, and account_value. This is bound to node closures at graph-build time so LangGraph node functions receive it alongside state.

### Node Functions
Four async node functions, each wrapping its PydanticAI agent:
- `_scan_node`: Builds ScannerDeps from state + deps, calls run_scanner, converts output to dict list
- `_strategist_node`: Builds StrategistDeps (including risk limits from settings), calls run_strategist
- `_risk_node`: Builds RiskAgentDeps with trade_proposals from state, calls run_risk_agent
- `_executor_node`: Filters to approved assessments, builds ExecutorDeps, calls run_executor

All nodes handle errors gracefully -- on exception, they return empty results with an `aborted_at` marker and log the error.

### Routing Functions
- `route_after_scan`: Returns "strategist" if opportunities list is non-empty, else END
- `route_after_risk`: Returns "executor" if any risk_assessments have approved=True, else END

### create_pipeline Factory
Builds the StateGraph, adds 4 nodes with deps bound via lambda closures, wires edges (START -> scanner -> conditional -> strategist -> risk_manager -> conditional -> executor -> END), and compiles with optional checkpointer.

### run_pipeline Convenience Function
Generates a UUID run_id (or accepts one), creates initial PipelineState with empty lists, invokes the graph with thread_id config for checkpoint isolation, and logs completion stats.

## Decisions Made

1. **Closure-bound deps for node functions** -- LangGraph node functions accept only state, so PipelineDeps is captured via closure in `create_pipeline()` rather than threaded through state or globals.

2. **Simple emptiness check for routing** -- `route_after_scan` checks `bool(opportunities)`, not a minimum count. Even one opportunity is worth evaluating.

3. **Graceful error handling in all nodes** -- Nodes catch all exceptions and return partial state with `aborted_at` set, rather than propagating errors that would crash the pipeline.

## Deviations from Plan

None -- plan executed exactly as written.

## Verification

- `python -c "from trading.agents.pipeline import create_pipeline, run_pipeline, PipelineDeps"` -- passes
- Routing functions tested: empty opps -> END, opps present -> strategist, no approvals -> END, approvals -> executor
- PipelineDeps has all 9 required fields

## Next Phase Readiness

Plan 05-06 (agent decision logging) can hook into node functions to persist reasoning chains. Plan 05-07 (app wiring) will create PipelineDeps from TradingApp attributes and call create_pipeline. The pipeline is complete and ready for integration.
