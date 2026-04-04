---
phase: 05-core-agent-pipeline
plan: "03"
subsystem: agent-pipeline
tags: [pydantic-ai, strategist, options, agent, tools]
depends_on:
  requires: ["05-01"]
  provides: ["strategist_agent", "StrategistDeps", "run_strategist"]
  affects: ["05-04", "05-05", "05-07"]
tech-stack:
  added: []
  patterns: ["PydanticAI agent with typed deps and structured output", "JSON tool return with error wrapping"]
key-files:
  created:
    - src/trading/agents/strategist.py
  modified: []
decisions:
  - id: "05-03-01"
    decision: "Strategist request_limit defaults to 15 (vs scanner's 10) because strategist makes more tool calls per run"
    rationale: "Each opportunity requires get_option_chain + get_current_price + get_risk_limits calls"
metrics:
  duration: "2min"
  completed: "2026-04-04"
---

# Phase 5 Plan 3: Strategist Agent Summary

Strategist PydanticAI agent that constructs complete trade proposals from scanner opportunities using real option chain data from ContractResolver, current prices from Redis, and risk limits from RiskLimitsProfile.

## What Was Done

### Task 1: Create strategist agent with option chain and pricing tools
- **StrategistDeps** dataclass: contract_resolver, iv_engine, redis_client, risk_limits (RiskLimitsProfile), account_value, opportunities, settings
- **strategist_agent** Agent: output_type=StrategistOutput, deps_type=StrategistDeps, model=None (resolved at runtime from config)
- **System prompt** enforces: (1) must use get_option_chain before proposing trades, (2) select strikes FROM available chain only, (3) respect risk limits, (4) include max_loss/max_profit/probability_of_profit
- **4 tools**: get_option_chain (ContractResolver), get_current_price (Redis), get_risk_limits (RiskLimitsProfile), get_opportunities (scanner output)
- **run_strategist** helper: resolves model from config, applies UsageLimits(request_limit=15, response_tokens_limit=4000), returns (StrategistOutput, Usage, messages)
- All tools wrap exceptions in JSON error responses (LLM-interpretable)

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Strategist request_limit=15 (vs scanner's 10) | Each opportunity requires multiple tool calls (chain + price + limits) |
| Option chain tool returns full strikes/expirations without truncation | LLM needs complete data to select appropriate strikes; truncation could hide valid strikes |
| model=None on agent, resolved at runtime | Follows scanner pattern: model comes from config via get_model("strategist") |
| Tools return JSON strings (not dicts) | PydanticAI tool return type must be str for LLM consumption |

## Deviations from Plan

None -- plan executed exactly as written.

## Commit History

| Commit | Type | Description |
|--------|------|-------------|
| 47166af | feat | Create strategist agent with option chain and pricing tools |

## Verification Results

- `python -c "from trading.agents.strategist import strategist_agent, StrategistDeps, run_strategist"` -- imports without error
- output_type is StrategistOutput (verified programmatically)
- 4 registered tools: get_option_chain, get_current_price, get_risk_limits, get_opportunities
- ctx.deps.contract_resolver pattern present (key_link verified)
- 287 lines (min 80 required)

## Next Phase Readiness

No blockers. Strategist agent is ready for:
- **05-04**: Risk manager agent can receive StrategistOutput proposals
- **05-05**: LangGraph pipeline can call run_strategist in strategist node
- **05-07**: Unit tests can mock StrategistDeps for isolated testing
