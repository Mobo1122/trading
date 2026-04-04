---
phase: 05-core-agent-pipeline
plan: 06
subsystem: agents
tags: [agent-logging, decision-audit, reasoning-chain, token-tracking, pipeline-persistence]

# Dependency graph
requires:
  - phase: 05-01
    provides: "AgentDecisionLog ORM model and agent_decision_log table schema"
  - phase: 05-05
    provides: "LangGraph pipeline node functions (scan/strategist/risk/executor)"
provides:
  - "log_agent_decision() async function for non-fatal DB persistence of agent decisions"
  - "STAGE_ORDER constant mapping agent names to pipeline positions"
  - "Full message history serialization via pydantic_core.to_jsonable_python"
  - "Per-node timing (duration_ms) and input summaries in pipeline"
affects:
  - phase: 05-07
    how: "Unit tests must verify logging integration in pipeline nodes"
  - phase: 07
    how: "Dashboard can query agent_decision_log for reasoning chain display"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Non-fatal DB persistence (try/except wrapper, matches 03-05/04-03 pattern)"
    - "time.monotonic() for wall-clock duration measurement in async nodes"
    - "pydantic_core.to_jsonable_python for PydanticAI message serialization"

# File tracking
key-files:
  created:
    - src/trading/agents/logging.py
  modified:
    - src/trading/agents/pipeline.py

# Decisions
decisions:
  - id: "05-06-01"
    decision: "Logging errors are non-fatal (try/except wrapping entire log_agent_decision)"
    rationale: "Matches project-wide pattern from 03-05 and 04-03. Audit logging must never crash the trading pipeline."
  - id: "05-06-02"
    decision: "model_name left as None since Usage object does not expose it"
    rationale: "PydanticAI Usage class has no model_name attribute. Column exists for future use when model info is available."
  - id: "05-06-03"
    decision: "Input summaries are descriptive strings per node rather than raw data"
    rationale: "Human-readable summaries are more useful for audit review than serialized raw input data."

# Metrics
metrics:
  duration: "4min"
  completed: "2026-04-04"
  tasks: 2
  commits: 2
---

# Phase 5 Plan 06: Agent Decision Logging Summary

Non-fatal agent decision logger persisting full reasoning chain, messages, token usage, and structured output to agent_decision_log table, with timing integration in all four pipeline nodes.

## What Was Done

### Task 1: Create agent decision logger with DB persistence
Created `src/trading/agents/logging.py` with:
- `STAGE_ORDER` constant: `{"scanner": 1, "strategist": 2, "risk_manager": 3, "executor": 4}`
- `log_agent_decision()` async function that constructs an `AgentDecisionLog` record and persists it via the session factory
- Message serialization via `json.dumps(to_jsonable_python(messages))` from pydantic_core
- Output serialization via `output.model_dump_json()`
- Reasoning extraction from `output.reasoning` attribute
- Token count extraction from PydanticAI `Usage` object (`request_tokens`, `response_tokens`)
- `_get_output_summary()` internal helper producing concise descriptions for each output type (e.g., "3 opportunities found", "2 proposals constructed", "1 assessed, 1 approved")
- Entire function wrapped in try/except with structlog warning on failure

### Task 2: Integrate logging into pipeline node functions
Updated all four node functions in `pipeline.py`:
- Added `time` and `log_agent_decision` imports
- Each node records `t0 = time.monotonic()` before agent run
- After successful run: computes `duration_ms`, calls `await log_agent_decision()` with output, messages, usage, duration, and input summary
- In error path: also logs with `error=str(exc)` and measured duration
- Input summaries per node:
  - Scanner: "5 symbols: SPY, QQQ, AAPL, ..."
  - Strategist: "3 opportunities from scanner"
  - Risk manager: "2 trade proposals from strategist"
  - Executor: "1 approved proposals for execution"

## Decisions Made

1. **Non-fatal logging** -- Logging errors caught and warned, never propagate. Matches 03-05/04-03 project pattern.
2. **model_name left as None** -- PydanticAI Usage does not expose model name. Column reserved for future enrichment.
3. **Descriptive input summaries** -- Human-readable strings (not raw JSON) for each pipeline stage input.

## Deviations from Plan

None -- plan executed exactly as written.

## Verification Results

- `from trading.agents.logging import log_agent_decision, STAGE_ORDER` -- imports successfully, STAGE_ORDER prints correct mapping
- `from trading.agents.pipeline import create_pipeline` -- imports successfully, all node functions compile

## Next Phase Readiness

Plan 05-07 (app lifecycle wiring and tests) can now test:
- `log_agent_decision()` DB persistence with mock session factory
- Pipeline node functions include logging calls with timing
- Error paths produce logged records with error strings
