---
phase: 05-core-agent-pipeline
plan: 04
subsystem: agents
tags: [pydantic-ai, risk-agent, executor-agent, redis-greeks, deterministic-risk, options-trading]

# Dependency graph
requires:
  - phase: 05-01
    provides: "Agent foundation (PydanticAI, models, config, scanner pattern)"
  - phase: 03-risk-engine
    provides: "RiskManager deterministic check_trade(), GreeksImpact, TradeProposal"
  - phase: 04-order-execution
    provides: "OrderExecutionService.submit_order() with risk gate"
  - phase: 02-market-data-analytics
    provides: "Redis market data cache with mktdata:latest:greeks:{con_id} HSET keys"
provides:
  - "Risk manager PydanticAI agent (risk_agent, RiskAgentDeps, run_risk_agent)"
  - "Executor PydanticAI agent (executor_agent, ExecutorDeps, run_executor)"
  - "Real Greeks lookup from Redis cache for deterministic risk checks"
  - "Per-leg Greeks aggregation into GreeksImpact (quantity-weighted, sign-adjusted)"
affects: [05-05, 05-06, 05-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Deterministic-first agent: hard rules via tool THEN LLM qualitative layer"
    - "Double risk-gate: executor submit_trade calls submit_order which re-runs risk check"
    - "Redis SCAN + HGETALL pattern for Greeks lookup by symbol"
    - "Private async helper (_lookup_greeks) shared between tool and internal logic"

key-files:
  created:
    - "src/trading/agents/risk_agent.py"
    - "src/trading/agents/executor_agent.py"
  modified: []

key-decisions:
  - "Symbol-based Greeks matching (not con_id) as known simplification for portfolio-level exposure"
  - "Temperature 0.1 for risk agent (slight flexibility), 0.0 for executor (pure execution)"
  - "Executor response_tokens_limit capped at 2000 (smaller than default 4000)"

patterns-established:
  - "Deterministic-first risk: tool runs RiskManager.check_trade() FIRST, LLM adds qualitative layer"
  - "Zero-fallback Greeks: on Redis cache miss, use zeros with structlog warning (non-fatal)"
  - "Per-leg aggregation: multiply delta/gamma/theta/vega by quantity, negate for SELL"

# Metrics
duration: 4min
completed: 2026-04-04
---

# Phase 5 Plan 04: Risk Manager and Executor Agents Summary

**Deterministic-first risk agent with real Greeks from Redis cache, and executor agent wrapping OrderExecutionService with double risk-gate protection**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-04T18:42:10Z
- **Completed:** 2026-04-04T18:46:26Z
- **Tasks:** 2/2
- **Files created:** 2

## Accomplishments
- Risk agent enforces deterministic-first architecture: Phase 3 RiskManager.check_trade() runs via tool BEFORE LLM provides qualitative assessment
- Risk agent fetches real Greeks from Phase 2 Redis market data cache (mktdata:latest:greeks:* HSET keys) for each proposed leg
- Per-leg Greeks aggregated into GreeksImpact (quantity-weighted, sign-adjusted for BUY/SELL) so Phase 3 RISK-02 Greek exposure limits evaluate actual portfolio impact
- Executor agent delegates to OrderExecutionService.submit_order() which internally re-runs evaluate_with_failsafe() -- double risk-gate protection

## Task Commits

Each task was committed atomically:

1. **Task 1: Create risk manager agent with deterministic-first architecture and real Greeks lookup** - `b5ec198` (feat)
2. **Task 2: Create executor agent wrapping OrderExecutionService** - `a5cef63` (feat)

## Files Created/Modified
- `src/trading/agents/risk_agent.py` - Risk manager PydanticAI agent: RiskAgentDeps, _lookup_greeks helper, get_contract_greeks/check_deterministic_risk/get_trade_proposals tools, run_risk_agent
- `src/trading/agents/executor_agent.py` - Executor PydanticAI agent: ExecutorDeps, submit_trade/get_approved_trades tools, run_executor

## Decisions Made
- Symbol-based Greeks matching via Redis SCAN (not con_id resolution): Known simplification since ProposedLeg lacks con_id. Matches by symbol field in HSET. Future enhancement can add ContractResolver.qualify_options() for exact matching.
- Temperature 0.1 for risk agent (allows slight qualitative flexibility), 0.0 for executor (pure execution, no creativity)
- Executor UsageLimits response_tokens_limit capped at 2000 (vs default 4000) since executor responses are short status reports
- _lookup_greeks is a private async function (not a PydanticAI tool) shared between get_contract_greeks tool and check_deterministic_risk internal logic

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- All four pipeline agents now exist: scanner (05-02*), strategist (05-03*), risk_agent (05-04), executor_agent (05-04)
- Ready for 05-05 (LangGraph pipeline wiring) to compose agents into StateGraph nodes
- Ready for 05-06 (agent decision logging) to add audit trail
- Risk agent requires Redis and RiskManager at runtime; executor requires IB connection and OrderExecutionService

*scanner was 05-01 plan artifact, strategist in 05-03

---
*Phase: 05-core-agent-pipeline*
*Completed: 2026-04-04*
