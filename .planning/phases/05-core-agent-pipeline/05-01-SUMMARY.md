# Phase 5 Plan 1: Agent Foundation -- Dependencies, Config, Contracts, State Summary

**One-liner:** PydanticAI + LangGraph installed with shared AgentConfig, typed output contracts for all four pipeline stages, LangGraph TypedDict state, Postgres checkpoint factory, and agent_decision_log audit table.

## What Was Done

### Task 1: Install dependencies, create agent config, and shared output models
- Added `pydantic-ai-slim[anthropic]`, `langgraph`, `langgraph-checkpoint-postgres`, `psycopg[binary]` to pyproject.toml
- Created `src/trading/agents/` package with `__init__.py`
- Created `AgentConfig` Pydantic model with per-agent model overrides, temperature, token limits, and psycopg checkpoint connection string
- Defined 10 structured output contracts: `Opportunity`, `ScannerOutput`, `ProposedLeg`, `StrategyProposal`, `StrategistOutput`, `RiskAssessment`, `RiskManagerOutput`, `ExecutionResult`, `ExecutorOutput`, `PipelineResult`
- All models have `Field(description=...)` for LLM schema generation
- Integrated `AgentConfig` into `Settings` class with YAML defaults in `config/default.yml`
- **Commit:** `1eaf08d`

### Task 2: Create LangGraph pipeline state, checkpoint factory, DB migration, and Alembic exclusion
- Created `PipelineState` TypedDict with `list[dict]` fields for JSON-serializable checkpoint persistence
- Created `create_checkpointer()` async factory with `+asyncpg` connection string validation
- Added `AgentDecisionLog` ORM model with full audit fields (run_id, agent_name, stage_order, reasoning, messages_json, output_json, token usage, duration, error)
- Created Alembic migration 005 for `agent_decision_log` table with 3 indexes
- Updated `alembic/env.py` with `include_object` filter excluding LangGraph checkpoint tables (`checkpoint*`, `channel_values*`, `writes*`)
- **Commit:** `3c25b3e`

## Verification Results

All verification checks passed:
- `pydantic_ai.Agent` and `langgraph.graph.StateGraph` importable
- All 10 output contracts importable from `trading.agents.models`
- `PipelineState` importable from `trading.agents.state`
- `create_checkpointer` importable from `trading.agents.checkpoint`
- `Settings().agents.model` returns `anthropic:claude-sonnet-4-6`
- `AgentDecisionLog.__tablename__` returns `agent_decision_log`
- Migration file `005_agent_decision_log_schema.py` exists
- All 204 existing tests still pass (no regressions)

## Deviations from Plan

None -- plan executed exactly as written.

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Used `pydantic-ai-slim[anthropic]` instead of full `pydantic-ai` | Avoids pulling in Logfire dependency (per RESEARCH.md) |
| `list[dict]` in PipelineState instead of Pydantic models | LangGraph TypedDict state must be JSON-serializable for checkpointing |
| psycopg connection string validation in checkpoint factory | Prevents silent driver mismatch (RESEARCH.md Pitfall 1) |
| LangGraph table exclusion via `include_object` callback | Prevents Alembic from dropping LangGraph-managed tables (RESEARCH.md Open Question 4) |
| `agent_decision_log` as regular table (not hypertable) | Agent decisions are low-frequency, not time-series data |

## Key Files

### Created
- `src/trading/agents/__init__.py` -- Package marker
- `src/trading/agents/config.py` -- AgentConfig with per-agent model overrides
- `src/trading/agents/models.py` -- 10 structured output contracts
- `src/trading/agents/state.py` -- PipelineState TypedDict
- `src/trading/agents/checkpoint.py` -- AsyncPostgresSaver factory
- `alembic/versions/005_agent_decision_log_schema.py` -- Migration

### Modified
- `pyproject.toml` -- 4 new dependencies
- `config/default.yml` -- agents section with defaults
- `src/trading/config.py` -- AgentConfig integrated into Settings
- `src/trading/db/models.py` -- AgentDecisionLog ORM model
- `alembic/env.py` -- include_object exclusion filter

## Performance

- **Duration:** 5 minutes
- **Completed:** 2026-04-04
- **Tasks:** 2/2
- **Tests:** 204 passed, 0 failed
