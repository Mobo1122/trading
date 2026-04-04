# Phase 5: Core Agent Pipeline - Research

**Researched:** 2026-04-04
**Domain:** LLM agent orchestration (PydanticAI + LangGraph) for autonomous options trading
**Confidence:** MEDIUM (combination pattern is proven but integration specifics require prototyping)

## Summary

Phase 5 layers AI agent intelligence onto the deterministic foundation built in Phases 1-4. The standard approach in production AI agent systems as of early 2026 is to combine PydanticAI (v1.77.0) for individual agent logic with structured outputs, and LangGraph (v1.1.6) for multi-agent pipeline orchestration with state persistence. PydanticAI handles *what* each agent does (tools, structured output schemas, LLM interaction), while LangGraph handles *when* and *where* agents execute (graph-based routing, checkpointing, state management).

The existing codebase already uses Pydantic extensively (risk models, market data models, config), so PydanticAI is a natural fit. The project uses asyncpg for SQLAlchemy database access, but LangGraph's checkpoint-postgres uses psycopg3 -- these are independent drivers that can coexist connecting to the same PostgreSQL database on separate connections. Each agent (scanner, strategist, risk manager, executor) should be a PydanticAI Agent with a typed `output_type` Pydantic model, wired as a node function in a LangGraph StateGraph.

The key blocker identified in STATE.md -- "LangGraph + PydanticAI combined integration pattern has sparse documentation" -- is confirmed. The combination pattern is documented in community articles and blog posts but lacks official documentation from either project. The pattern is straightforward in concept (PydanticAI agents called inside LangGraph node functions), but integration nuances (shared state, error propagation, checkpoint serialization of Pydantic models) require a prototyping spike in plan 05-01.

**Primary recommendation:** Use PydanticAI agents as the agent abstraction layer with typed outputs, embedded inside LangGraph StateGraph node functions for pipeline orchestration. Start with an integration spike to validate the pattern before building domain logic.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic-ai | 1.77.0 | Agent framework with structured output | Type-safe LLM interaction, Pydantic ecosystem native, built-in output validation and retry |
| langgraph | 1.1.6 | Pipeline orchestration and state graph | Production-grade state machines, checkpointing, conditional routing, async-native |
| langgraph-checkpoint-postgres | 3.0.5 | Postgres checkpoint backend for LangGraph | Durable state persistence using existing Postgres, production-grade |
| anthropic | (latest) | Claude API SDK | Transitive dep of pydantic-ai[anthropic], needed for ANTHROPIC_API_KEY auth |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| psycopg[binary] | 3.x | Postgres driver for LangGraph checkpointer | Required by langgraph-checkpoint-postgres (separate from project's asyncpg) |
| pydantic-ai-slim[anthropic] | 1.77.0 | Minimal PydanticAI install with Anthropic support | If avoiding Logfire dependency; the full `pydantic-ai` includes Logfire |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| PydanticAI | LangChain Agents | LangChain is heavier, less type-safe; PydanticAI aligns with existing Pydantic usage |
| LangGraph | Custom asyncio pipeline | LangGraph adds checkpointing, conditional routing, state persistence for free |
| Anthropic Claude | OpenAI GPT | Claude has strong structured output; project can swap models later via PydanticAI model abstraction |
| langgraph-checkpoint-postgres | InMemorySaver | InMemorySaver loses state on restart; Postgres checkpoints survive crashes |

**Installation:**
```bash
pip install "pydantic-ai-slim[anthropic]" langgraph langgraph-checkpoint-postgres "psycopg[binary]"
```

Or add to pyproject.toml dependencies:
```toml
dependencies = [
    # ... existing deps ...
    "pydantic-ai-slim[anthropic]>=1.77.0",
    "langgraph>=1.1.6",
    "langgraph-checkpoint-postgres>=3.0.5",
    "psycopg[binary]>=3.1.0",
]
```

## Architecture Patterns

### Recommended Project Structure
```
src/trading/
├── agents/                    # Phase 5: Agent pipeline
│   ├── __init__.py
│   ├── config.py              # AgentConfig (model, temperature, token limits)
│   ├── models.py              # Shared Pydantic output models for agent contracts
│   ├── scanner.py             # Scanner PydanticAI agent
│   ├── strategist.py          # Strategist PydanticAI agent
│   ├── risk_agent.py          # Risk manager PydanticAI agent
│   ├── executor_agent.py      # Executor PydanticAI agent
│   ├── pipeline.py            # LangGraph StateGraph definition
│   ├── state.py               # LangGraph shared state model
│   ├── checkpoint.py          # Postgres checkpoint factory
│   └── logging.py             # Agent reasoning chain logger
├── app.py                     # Extended with Phase 5 wiring
├── config.py                  # Extended with AgentConfig section
└── ...                        # Existing Phase 1-4 modules
```

### Pattern 1: PydanticAI Agent with Typed Output
**What:** Each agent is a PydanticAI Agent with a Pydantic model as output_type, ensuring every LLM response is validated and structured.
**When to use:** Every agent in the pipeline.
**Example:**
```python
# Source: https://ai.pydantic.dev/agent/ and https://ai.pydantic.dev/output/
from dataclasses import dataclass
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

class ScannerOutput(BaseModel):
    """Structured output from the scanner agent."""
    opportunities: list[Opportunity] = Field(description="Identified trading opportunities")
    reasoning: str = Field(description="Natural language explanation of scan logic")
    scan_timestamp: datetime

@dataclass
class ScannerDeps:
    """Dependencies injected into scanner agent tools."""
    iv_engine: IVEngine
    redis_client: Any
    session_factory: Any
    watchlist: list[str]

scanner_agent = Agent(
    'anthropic:claude-sonnet-4-6',
    output_type=ScannerOutput,
    deps_type=ScannerDeps,
    instructions="You are a trading opportunity scanner...",
)

@scanner_agent.tool
async def get_iv_analytics(ctx: RunContext[ScannerDeps], symbol: str) -> str:
    """Get IV rank and percentile for a symbol."""
    iv_data = await ctx.deps.iv_engine.compute(symbol)
    return iv_data.model_dump_json()
```

### Pattern 2: LangGraph Node Wrapping PydanticAI Agent
**What:** Each LangGraph node function calls a PydanticAI agent, extracts structured output, and updates the shared graph state.
**When to use:** Every node in the pipeline graph.
**Example:**
```python
# Source: https://www.dotzlaw.com/insights/combining-the-power-of-langgraph-with-pydantic-ai-agents/
from langgraph.graph import StateGraph, START, END

async def scan_node(state: PipelineState) -> dict:
    """LangGraph node that runs the scanner agent."""
    deps = ScannerDeps(
        iv_engine=state.iv_engine,
        redis_client=state.redis_client,
        session_factory=state.session_factory,
        watchlist=state.watchlist,
    )
    result = await scanner_agent.run(
        f"Scan the following symbols for opportunities: {state.watchlist}",
        deps=deps,
    )
    return {
        "opportunities": result.output.opportunities,
        "scanner_reasoning": result.output.reasoning,
        "scanner_messages": result.all_messages(),
    }
```

### Pattern 3: LangGraph StateGraph with Conditional Routing
**What:** The pipeline graph routes between agents based on state, with conditional edges for error handling and empty results.
**When to use:** The main pipeline orchestration.
**Example:**
```python
# Source: https://docs.langchain.com/oss/python/langgraph/graph-api
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END

class PipelineState(TypedDict):
    """Shared state flowing through the agent pipeline."""
    watchlist: list[str]
    opportunities: list[dict]
    trade_proposals: list[dict]
    risk_decisions: list[dict]
    execution_results: list[dict]
    scanner_reasoning: str
    strategist_reasoning: str
    risk_reasoning: str
    executor_reasoning: str

def route_after_scan(state: PipelineState) -> str:
    """Route to strategist if opportunities found, else END."""
    if state.get("opportunities"):
        return "strategist"
    return END

def route_after_risk(state: PipelineState) -> str:
    """Route to executor if any proposals approved, else END."""
    approved = [d for d in state.get("risk_decisions", []) if d.get("approved")]
    if approved:
        return "executor"
    return END

workflow = StateGraph(PipelineState)
workflow.add_node("scanner", scan_node)
workflow.add_node("strategist", strategist_node)
workflow.add_node("risk_manager", risk_node)
workflow.add_node("executor", executor_node)

workflow.add_edge(START, "scanner")
workflow.add_conditional_edges("scanner", route_after_scan)
workflow.add_edge("strategist", "risk_manager")
workflow.add_conditional_edges("risk_manager", route_after_risk)
workflow.add_edge("executor", END)

# Compile with Postgres checkpointer
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
checkpointer = AsyncPostgresSaver.from_conn_string(
    "postgresql://trading:trading@localhost:5432/trading"
)
await checkpointer.setup()
graph = workflow.compile(checkpointer=checkpointer)
```

### Pattern 4: Agent Reasoning Chain Logging
**What:** Every agent decision is logged with full reasoning as structured data, combining structlog (existing project pattern) with PydanticAI message capture.
**When to use:** Every agent node after the run completes.
**Example:**
```python
# Custom logging pattern for audit trail
import structlog

log = structlog.get_logger("trading.agents")

async def scan_node(state: PipelineState) -> dict:
    result = await scanner_agent.run(prompt, deps=deps)

    # Log the full reasoning chain
    log.info(
        "agent.scanner.complete",
        reasoning=result.output.reasoning,
        num_opportunities=len(result.output.opportunities),
        input_tokens=result.usage().request_tokens,
        output_tokens=result.usage().response_tokens,
        model=result.usage().model_name if hasattr(result.usage(), 'model_name') else "unknown",
    )

    # Persist messages for audit trail
    all_messages = result.all_messages()
    # Serialize and store in DB (agent_decision_log table)
    ...
```

### Pattern 5: Dependency Injection from TradingApp
**What:** Agent dependencies (IV engine, risk manager, execution service, etc.) flow from TradingApp through the LangGraph state into PydanticAI agent deps.
**When to use:** Connecting Phase 1-4 infrastructure to agents.
**Example:**
```python
# In TradingApp.startup() or connect_ib():
# Phase 5: Agent pipeline (created after all infrastructure)
self.agent_pipeline = create_pipeline(
    iv_engine=self.iv_engine,
    earnings_calendar=self.earnings_calendar,
    risk_manager=self.risk_manager,
    execution_service=self.execution_service,
    redis_client=self.redis_client,
    session_factory=self.session_factory,
    settings=self.settings,
)
```

### Anti-Patterns to Avoid
- **Passing IB connection into agent tools directly:** Agents should use the existing service layer (IVEngine, ExecutionService, RiskManager), not raw IB API calls. This maintains the safety guarantees from Phases 1-4.
- **Letting LLM decide risk limits:** The risk manager agent ADDS qualitative LLM risk assessment ON TOP of the deterministic risk engine from Phase 3. It never bypasses or overrides the deterministic checks.
- **Storing raw LLM text in graph state:** Always use Pydantic validated structured output. Raw text is unreliable for downstream processing.
- **Running agents without usage limits:** Always set `usage_limits=UsageLimits(request_limit=N, response_tokens_limit=N)` to prevent runaway token consumption.
- **Synchronous agent calls in async pipeline:** Always use `await agent.run()`, never `agent.run_sync()` in the LangGraph pipeline since the existing codebase is async-first.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| LLM structured output | Custom JSON parsing of LLM text | PydanticAI output_type with Pydantic model | PydanticAI handles schema generation, validation, retry on malformed output |
| Pipeline state persistence | Custom DB tables for pipeline state | LangGraph checkpointer (AsyncPostgresSaver) | Handles serialization, threading, time-travel debugging, crash recovery |
| Agent retry on bad output | Manual retry loops around LLM calls | PydanticAI built-in retries + output validators | Framework handles reflection-based retry, sends validation errors back to LLM |
| Multi-agent routing | Custom if/else orchestration | LangGraph conditional edges | Graph-based routing with visualization, debugging, checkpoint at each step |
| Tool argument validation | Manual parameter checking | PydanticAI tool decorator + type hints | Framework validates tool args via Pydantic, sends errors back to LLM for retry |
| Token usage tracking | Custom counting code | PydanticAI result.usage() | Built into the framework, includes request/response tokens per run |
| Message history serialization | Custom JSON serialization | PydanticAI ModelMessagesTypeAdapter | Built-in serialization/deserialization of full message history |

**Key insight:** The PydanticAI + LangGraph combination eliminates most boilerplate in building agent pipelines. Building custom solutions for structured output, state management, or orchestration would be months of work and would lack the robustness of these frameworks.

## Common Pitfalls

### Pitfall 1: psycopg vs asyncpg Driver Conflict
**What goes wrong:** The existing project uses asyncpg (via SQLAlchemy `postgresql+asyncpg://`), but langgraph-checkpoint-postgres requires psycopg3. Installing both in the same project can cause confusion about which driver is used where.
**Why it happens:** LangGraph checkpointer uses psycopg directly (not through SQLAlchemy). Both drivers connect to the same Postgres database but on separate connections.
**How to avoid:** Keep the drivers isolated: asyncpg stays with SQLAlchemy ORM (all existing Phase 1-4 code), psycopg is used ONLY by LangGraph's AsyncPostgresSaver via its own connection string (without the `+asyncpg` prefix: `postgresql://trading:trading@localhost:5432/trading`). Never mix the drivers.
**Warning signs:** Import errors or connection pool exhaustion from having two independent connection pools.

### Pitfall 2: LLM Bypassing Deterministic Risk Gate
**What goes wrong:** The risk manager agent provides LLM-based risk assessment but could be architected to replace rather than supplement the deterministic risk engine from Phase 3.
**Why it happens:** The LLM can sound authoritative about risk and tempt developers to trust it over hard rules.
**How to avoid:** Architecture must be: deterministic risk check FIRST (existing RiskManager.check_trade()), then LLM risk assessment as an additional qualitative layer. The executor agent calls ExecutionService.submit_order() which internally calls evaluate_with_failsafe() -- this is non-negotiable.
**Warning signs:** If the risk agent produces approved/rejected decisions without calling the Phase 3 RiskManager, the safety architecture is broken.

### Pitfall 3: Runaway LLM Token Costs
**What goes wrong:** Agents in a loop or with large tool outputs consume excessive tokens, leading to high API costs.
**Why it happens:** Market data tool results can be large (option chains, full watchlist scans), and agents may make many tool calls per run.
**How to avoid:** Set UsageLimits on every agent run: `usage_limits=UsageLimits(request_limit=10, response_tokens_limit=4000)`. Summarize large data before returning from tools. Monitor per-pipeline-run token usage and alert if above threshold.
**Warning signs:** Monthly API bill exceeding expected per-trade cost. Individual agent runs consuming more than a few thousand tokens.

### Pitfall 4: Stale State in LangGraph Checkpoints
**What goes wrong:** Pipeline state persisted via checkpointing contains market data that is stale by the time the pipeline resumes.
**Why it happens:** Market data changes rapidly. If a pipeline is interrupted and resumed from a checkpoint, the opportunities identified by the scanner may no longer be valid.
**How to avoid:** Checkpoints should NOT store volatile market data. Instead, store identifiers (symbols, opportunity IDs) and re-fetch current data when the pipeline resumes. Add staleness checks at each node boundary.
**Warning signs:** Trades executed on data that is minutes or hours old.

### Pitfall 5: LangGraph Checkpoint Table Setup
**What goes wrong:** AsyncPostgresSaver requires `.setup()` to create its internal tables. Forgetting this causes runtime errors.
**Why it happens:** Unlike Alembic migrations which run at deploy time, the checkpointer setup is a runtime initialization step.
**How to avoid:** Call `await checkpointer.setup()` during application startup, similar to other non-critical bootstraps in connect_ib(). Use try/except with warning for resilience.
**Warning signs:** `relation "checkpoints" does not exist` errors at runtime.

### Pitfall 6: LLM Hallucinating Invalid Strike Prices or Expirations
**What goes wrong:** The strategist agent generates trade proposals with strikes or expirations that don't exist in the actual option chain.
**Why it happens:** LLMs generate plausible-looking numbers, not actual market data.
**How to avoid:** Strategist agent tools must provide actual available strikes/expirations from IB option chain data. The agent selects FROM the available set, never invents values. Output validation should cross-reference against option chain cache.
**Warning signs:** Trade proposals with strike prices that don't match any listed contract.

### Pitfall 7: Insufficient Agent Decision Logging
**What goes wrong:** Agent decisions are logged as opaque structured data without the natural-language reasoning chain, making it impossible to audit why a trade was made.
**Why it happens:** Developers log only the final output, not the reasoning process.
**How to avoid:** AGENT-06 requires full reasoning chain. Use `result.all_messages()` to capture the entire conversation including tool calls and responses. Store both the structured output AND the message history. The `reasoning` field in each agent's output model should contain a human-readable explanation.
**Warning signs:** Agent audit log shows only "bought SPY 450C" without explaining why.

## Code Examples

Verified patterns from official sources:

### Creating a PydanticAI Agent with Anthropic Claude
```python
# Source: https://ai.pydantic.dev/models/anthropic/
from pydantic_ai import Agent, ModelSettings, UsageLimits
from pydantic import BaseModel, Field

class StrategyProposal(BaseModel):
    """Output contract for the strategist agent."""
    symbol: str
    strategy_type: str = Field(description="e.g., iron_condor, vertical_spread")
    legs: list[ProposedLeg]
    reasoning: str = Field(description="Why this strategy was chosen")
    expected_max_loss: float
    expected_max_profit: float
    probability_of_profit: float = Field(ge=0, le=1)

strategist = Agent(
    'anthropic:claude-sonnet-4-6',
    output_type=StrategyProposal,
    instructions="You are an options strategist. Given opportunities, construct optimal trade proposals.",
    model_settings=ModelSettings(temperature=0.1, max_tokens=2000),
)

# Run with usage limits
result = await strategist.run(
    prompt,
    deps=deps,
    usage_limits=UsageLimits(request_limit=10, response_tokens_limit=4000),
)
print(result.output)  # Typed as StrategyProposal
print(result.usage())  # Token usage stats
```

### LangGraph Postgres Checkpointer Setup
```python
# Source: https://docs.langchain.com/oss/python/langgraph/persistence
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

# NOTE: Use plain postgresql:// (psycopg), NOT postgresql+asyncpg://
CHECKPOINT_CONN_STRING = "postgresql://trading:trading@localhost:5432/trading"

async def create_checkpointer() -> AsyncPostgresSaver:
    checkpointer = AsyncPostgresSaver.from_conn_string(CHECKPOINT_CONN_STRING)
    await checkpointer.setup()  # Creates checkpoint tables if not exist
    return checkpointer
```

### Running a LangGraph Pipeline with Thread ID
```python
# Source: https://docs.langchain.com/oss/python/langgraph/graph-api
import uuid

config = {
    "configurable": {
        "thread_id": str(uuid.uuid4()),  # Unique per pipeline run
    }
}

result = await graph.ainvoke(
    {
        "watchlist": ["SPY", "QQQ", "AAPL"],
        "opportunities": [],
        "trade_proposals": [],
        "risk_decisions": [],
        "execution_results": [],
    },
    config=config,
)
```

### PydanticAI Tool with Dependency Injection
```python
# Source: https://ai.pydantic.dev/tools/
from pydantic_ai import Agent, RunContext
from dataclasses import dataclass

@dataclass
class RiskAgentDeps:
    risk_manager: RiskManager
    session_factory: Any

risk_agent = Agent(
    'anthropic:claude-sonnet-4-6',
    output_type=RiskAssessment,
    deps_type=RiskAgentDeps,
    instructions="You validate trade proposals against risk rules...",
)

@risk_agent.tool
async def check_deterministic_risk(
    ctx: RunContext[RiskAgentDeps], proposal_json: str
) -> str:
    """Run the deterministic risk engine check on a trade proposal."""
    proposal = TradeProposal.model_validate_json(proposal_json)
    decision = await ctx.deps.risk_manager.check_trade(proposal)
    return decision.model_dump_json()
```

### Serializing Agent Messages for Audit Trail
```python
# Source: https://ai.pydantic.dev/message-history/
from pydantic_core import to_jsonable_python
import json

result = await scanner_agent.run(prompt, deps=deps)

# Serialize messages to JSON for DB storage
messages_json = json.dumps(to_jsonable_python(result.all_messages()))

# Later, deserialize
from pydantic_ai import ModelMessagesTypeAdapter
restored = ModelMessagesTypeAdapter.validate_json(messages_json)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| LangChain Agents | PydanticAI + LangGraph | 2025 | Separation of agent logic from orchestration; type-safe outputs |
| Custom JSON parsing of LLM output | PydanticAI structured output with validation | 2025 | Automatic schema generation, validation, retry on malformed output |
| InMemorySaver for dev only | AsyncPostgresSaver for all environments | LangGraph 1.0 (2025) | Durable state persistence, crash recovery, time-travel debugging |
| result_type parameter | output_type parameter | PydanticAI v1 (Sep 2025) | API rename, same functionality |
| langchain.agents | langgraph StateGraph | 2024-2025 | Explicit graph control replaces implicit agent loops |

**Deprecated/outdated:**
- `result_type` in PydanticAI: Renamed to `output_type` in v1.0. Use `output_type`.
- `result.data`: Renamed to `result.output` in PydanticAI v1.0. Use `result.output`.
- LangChain's AgentExecutor: Replaced by LangGraph for production multi-agent systems.
- `agent.run_sync()` in async contexts: Use `await agent.run()` in async code.

## Open Questions

Things that couldn't be fully resolved:

1. **LangGraph + PydanticAI Integration Nuances**
   - What we know: The pattern is "PydanticAI agents called inside LangGraph node functions." Community articles confirm this works.
   - What's unclear: How PydanticAI agent errors propagate through LangGraph state. Whether Pydantic output models serialize cleanly into LangGraph TypedDict state. How to handle partial pipeline failures with checkpoint recovery when PydanticAI retries have been exhausted.
   - Recommendation: Plan 05-01 should be a prototyping spike that validates the integration pattern end-to-end before building domain logic.

2. **psycopg + asyncpg Connection Pool Sizing**
   - What we know: Both drivers connect to the same Postgres. asyncpg has pool_size=10, pool_overflow=5 configured.
   - What's unclear: What connection pool LangGraph's AsyncPostgresSaver uses and whether it can be configured to avoid exhausting Postgres connections.
   - Recommendation: Monitor total Postgres connections during testing. May need to increase max_connections or use a connection pooler like PgBouncer.

3. **Anthropic Claude Model Selection for Trading**
   - What we know: PydanticAI supports `anthropic:claude-sonnet-4-6` and other Claude models. Sonnet is the balanced cost/performance model.
   - What's unclear: Whether Claude Sonnet has sufficient financial domain knowledge for options strategy construction. Whether Claude Haiku (cheaper) is sufficient for scanner/executor agents that do simpler tasks.
   - Recommendation: Start with Sonnet for all agents, then optimize per-agent model selection based on output quality and cost observations. Make model configurable per agent.

4. **LangGraph Checkpoint Table Naming vs Alembic**
   - What we know: AsyncPostgresSaver.setup() creates its own tables. The project uses Alembic for schema migrations.
   - What's unclear: Whether LangGraph's auto-created tables conflict with Alembic migration tracking. Whether Alembic will try to drop them as "unmanaged."
   - Recommendation: Add LangGraph checkpoint tables to Alembic's `include_object` exclusion list so they are ignored by autogenerate.

5. **Token Cost Per Pipeline Run**
   - What we know: Each agent makes at least one LLM call. Tool calls add tokens. Claude Sonnet pricing is per-token.
   - What's unclear: The total token cost per full scanner->strategist->risk->executor pipeline run with realistic market data.
   - Recommendation: Instrument from day one. Track per-agent and per-pipeline token usage. Set hard limits via UsageLimits. Budget estimation should be part of prototyping spike.

## Sources

### Primary (HIGH confidence)
- PydanticAI official docs (https://ai.pydantic.dev/) - Agent API, tools, output types, message history, Anthropic model support
- PydanticAI PyPI (https://pypi.org/project/pydantic-ai/) - Version 1.77.0, released 2026-04-03
- LangGraph official docs (https://docs.langchain.com/oss/python/langgraph/) - StateGraph API, persistence, checkpointing
- LangGraph PyPI (https://pypi.org/project/langgraph/) - Version 1.1.6, released 2026-04-03
- langgraph-checkpoint-postgres PyPI (https://pypi.org/project/langgraph-checkpoint-postgres/) - Version 3.0.5, psycopg requirement

### Secondary (MEDIUM confidence)
- Dotzlaw Consulting article on LangGraph + PydanticAI integration (https://www.dotzlaw.com/insights/combining-the-power-of-langgraph-with-pydantic-ai-agents/) - Validated pattern of agents as nodes
- Multiple 2026 framework comparison articles confirming PydanticAI + LangGraph as standard combination pattern
- LangGraph GitHub issues confirming psycopg3 as required driver for checkpoint-postgres

### Tertiary (LOW confidence)
- Community blog posts on financial trading agents with LangGraph (pattern inspiration, not verified for production)
- Medium articles on LangGraph checkpointing best practices (single-source, needs validation)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Versions verified via PyPI, APIs verified via official docs
- Architecture: MEDIUM - Combination pattern confirmed by multiple sources, but integration specifics require prototyping spike
- Pitfalls: MEDIUM - Driver conflict identified from official docs; other pitfalls based on general LLM agent production patterns and multiple corroborating sources
- Code examples: HIGH - Drawn from official PydanticAI and LangGraph documentation

**Research date:** 2026-04-04
**Valid until:** 2026-04-18 (14 days -- fast-moving domain, both frameworks release frequently)
