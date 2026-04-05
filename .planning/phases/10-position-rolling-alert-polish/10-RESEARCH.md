# Phase 10: Position Rolling Pipeline & Alert Polish - Research

**Researched:** 2026-04-05
**Domain:** LangGraph pipeline node extension, ExpirationMonitor activation, Slack Block Kit formatting
**Confidence:** HIGH

## Summary

Phase 10 closes the last three tech debt items from the v1 milestone audit. The work splits into two orthogonal concerns: (1) activating the dead rolling code by adding a pipeline node that consumes `rolling_candidates` from PipelineState and routes them through the existing strategist -> risk -> executor chain, and (2) adding a dedicated `_blocks_trade_rejected` handler to SlackNotifier so trade rejection alerts display with structured Block Kit formatting instead of the generic JSON fallback.

All required infrastructure already exists. ExpirationMonitor (`src/trading/agents/rolling.py`) is fully implemented with `scan_expiring_positions()`, `evaluate_rolling()`, and `build_roll_proposals()`. PipelineState already has `rolling_candidates` and `rolling_decisions` fields. `app.py:run_agent_pipeline()` already calls `scan_expiring_positions()` and injects serialized candidates into the pipeline via the `rolling_candidates` parameter. The only missing piece is a pipeline node that reads `state["rolling_candidates"]`, calls `evaluate_rolling()` and `build_roll_proposals()`, and converts the resulting proposals into the format consumed by the strategist or executor. For the Slack side, SlackNotifier already has handlers for 6 of the 7 alert channels; `alerts:trade_rejected` is the sole missing handler.

**Primary recommendation:** Add a dedicated `_rolling_node` to the LangGraph StateGraph that runs after `regime_detector` but before `scanner` (or in parallel with scanning). The rolling node reads `rolling_candidates`, calls `ExpirationMonitor.evaluate_rolling()` and `build_roll_proposals()`, then converts roll proposals into trade proposals compatible with the strategist output format (or injects them directly into `trade_proposals` to bypass the LLM for deterministic rolls). Add `_blocks_trade_rejected` and update `_build_text` in SlackNotifier following the exact pattern of the existing 6 handlers.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| langgraph | (already installed) | StateGraph pipeline with conditional routing | Pipeline infrastructure already uses LangGraph; new node follows same pattern |
| pydantic | (already installed) | Data models for RollingCandidate, RollingDecision | All pipeline data models use Pydantic BaseModel with model_dump() |
| slack-sdk | (already installed) | AsyncWebhookClient for Block Kit messages | Already used by SlackNotifier for all other alert channels |
| structlog | (already installed) | Structured logging for rolling node | All pipeline nodes log via structlog |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest + pytest-asyncio | (already installed) | Async test fixtures and mock-based pipeline testing | All pipeline tests use this pattern |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Dedicated `_rolling_node` | Inject rolling into `_scan_node` | Dedicated node is cleaner separation; scan_node already complex; rolling is conceptually distinct from opportunity scanning |
| Dedicated `_rolling_node` | Inject directly into `_strategist_node` | Strategist expects scanner output format; rolling proposals have different fields; mixing concerns |
| Convert rolls to trade_proposals | Route through strategist LLM | Prior decision [06-02]: deterministic rolling (no LLM); safety-critical position management must be predictable |
| Single rolling node | Separate evaluate + execute nodes | Over-engineering; rolling evaluation + proposal building is a single logical step |

## Architecture Patterns

### Current Pipeline Topology (Pre-Phase 10)
```
START -> regime_detector -> scanner -> [conditional] -> strategist -> risk_manager -> [conditional] -> executor/approval_gate -> END
```

Rolling candidates flow: `app.run_agent_pipeline()` calls `scan_expiring_positions()`, serializes to dicts, passes into `run_pipeline(rolling_candidates=...)`, which injects them into `initial_state["rolling_candidates"]`. **But no node reads `state["rolling_candidates"]`.**

### Proposed Pipeline Topology (Post-Phase 10)
```
START -> regime_detector -> rolling_node -> scanner -> [conditional] -> strategist -> risk_manager -> [conditional] -> executor/approval_gate -> END
```

The `rolling_node` runs after regime detection (it does not need regime context) and before scanning. It consumes `rolling_candidates`, calls `evaluate_rolling()` + `build_roll_proposals()`, converts the proposals to `trade_proposals` format, and writes them to `state["rolling_decisions"]`. Downstream, the strategist node is modified to merge rolling proposals into its output (or the rolling proposals bypass the strategist entirely and go straight to risk_manager).

### Pattern 1: Rolling Node as Deterministic Pre-Processor
**What:** A new pipeline node `_rolling_node` that:
1. Reads `state["rolling_candidates"]` (serialized RollingCandidate dicts)
2. Deserializes them back to `RollingCandidate` objects
3. Calls `ExpirationMonitor.evaluate_rolling(candidates)` to get decisions
4. Calls `ExpirationMonitor.build_roll_proposals(decisions)` to get close/open proposals
5. Converts roll proposals into StrategyProposal-compatible dicts
6. Returns `{"rolling_decisions": decisions_as_dicts, "trade_proposals": merged_proposals}`

**When to use:** This is the right pattern because:
- Prior decision [06-02] mandates deterministic rolling (no LLM)
- Prior decision [06-02] mandates close-before-roll safety rule
- The ExpirationMonitor methods are already fully implemented and tested
- Proposals just need format conversion to work with existing risk/executor nodes

**Critical detail -- trade_proposals merging:** The rolling node must ADD its proposals to any existing `trade_proposals` in state (which will be empty at this point since scanner hasn't run yet). After scanner -> strategist produces more proposals, both the rolling proposals and scanner-driven proposals will be in `trade_proposals` for the risk node to evaluate. However, this creates a sequencing issue: the rolling node runs before strategist, so `trade_proposals` from rolling will already be set before strategist adds its own. With LangGraph TypedDict state, list fields use "replace" semantics by default unless an `Annotated[list, operator.add]` reducer is used.

**Resolution approach:** Two options:
- **Option A (simpler):** Rolling node writes to `rolling_decisions` only (for logging). A new field `rolling_proposals` in PipelineState holds the converted proposals. Then `_strategist_node` merges `rolling_proposals` into its output `trade_proposals`. This keeps concerns separate.
- **Option B (cleaner):** Rolling node writes roll proposals to a dedicated `rolling_proposals` field. After strategist runs, a simple merge step combines `rolling_proposals` and `trade_proposals` before risk evaluation. This could be done in `_risk_node` by reading both fields.
- **Option C (simplest, recommended):** The rolling node evaluates and builds proposals, writes them to `rolling_decisions`. Then `_risk_node` is updated to also process `rolling_decisions` by converting them to the same TradeProposal format and evaluating them alongside strategist proposals. This requires no PipelineState schema changes and the risk gate is the correct place to validate all proposals.

**Recommended: Option C.** It requires zero new PipelineState fields, keeps the rolling node focused on evaluation/decision, and ensures all proposals (both scanner-driven and rolling-driven) pass through the same risk gate.

### Pattern 2: Rolling Proposal to Risk-Compatible Format
**What:** Converting `build_roll_proposals()` output dicts into dicts that `_risk_node` / `_executor_node` can process.

The existing risk_agent expects `trade_proposals` with this shape (from StrategyProposal):
```python
{
    "symbol": str,
    "strategy_type": str,  # e.g., "roll_close", "roll_open"
    "legs": [{"symbol": str, "right": str, "strike": float, "expiry": str, "action": str, "quantity": int}],
    "max_loss": float,
    "max_profit": float,
    "probability_of_profit": float,
    "reasoning": str,
}
```

The `build_roll_proposals()` output already has: symbol, right, strike, expiry, action, quantity, strategy_type, reasoning, con_id. The conversion needs to wrap each proposal into the StrategyProposal shape with a single-leg `legs` list and populate max_loss/max_profit/probability_of_profit with conservative estimates.

### Pattern 3: SlackNotifier Handler Addition
**What:** Adding `_blocks_trade_rejected` and updating `_build_text` / `_build_blocks` dispatch.

The existing pattern in `slack.py` is:
1. `_build_text()` has an `if channel == "alerts:X": return formatted_string` branch per channel
2. `_build_blocks()` has an `if channel == "alerts:X": return self._blocks_X(data)` branch per channel
3. Each `_blocks_X()` method returns a `list[dict]` of Block Kit blocks

There are two sources of `alerts:trade_rejected` events:
1. **Executor rejection** (pipeline.py:527-534): `{"symbol": proposal_id, "reason": details, "status": status, "run_id": run_id}`
2. **Approval rejection/timeout** (pipeline.py:680-687): `{"approval_id": approval_id, "reason": result, "symbols": [...], "run_id": run_id}`

The handler must gracefully handle both payload shapes.

### Anti-Patterns to Avoid
- **Routing rolling through the LLM strategist:** Prior decision [06-02] explicitly forbids this. Rolling logic is deterministic. The LLM is unpredictable and could suggest inappropriate rolls.
- **Skipping the risk gate for rolls:** Even though rolling decisions are deterministic, they MUST pass through the risk gate. The close-before-roll safety rule [06-02] handles the catastrophic loss case, but the risk gate handles position limits, Greeks exposure, and portfolio-level constraints.
- **Modifying ExpirationMonitor's existing methods:** The methods are fully implemented and tested. The rolling node should call them as-is, not modify them.
- **Adding interactive buttons to trade_rejected messages:** The trade_rejected alert is informational (the trade was already rejected). Interactive buttons are only needed for approval_request.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Pipeline node wiring | Custom event loop or callback chain | LangGraph `workflow.add_node()` + `workflow.add_edge()` | Consistent with existing 6 nodes; handles state serialization, error propagation, checkpointing |
| Rolling decision logic | New decision engine | Existing `ExpirationMonitor.evaluate_rolling()` + `build_roll_proposals()` | Already implemented, tested, and follows prior decision [06-02] deterministic requirements |
| Slack Block Kit formatting | Custom JSON builder | Follow existing `_blocks_*()` method pattern in SlackNotifier | All 6 existing handlers use the same pattern; consistency is critical |
| Trade proposal format conversion | Custom serialization | `RollingCandidate.model_dump()` / `RollingDecision.model_dump()` | Pydantic serialization is already used everywhere in the pipeline |

**Key insight:** This phase is almost entirely wiring and format conversion. Every logical component already exists -- the work is connecting them.

## Common Pitfalls

### Pitfall 1: LangGraph List State Replacement Semantics
**What goes wrong:** LangGraph TypedDict state uses "last write wins" for all fields by default. If `_rolling_node` writes `trade_proposals`, it will be overwritten when `_strategist_node` also writes `trade_proposals`.
**Why it happens:** LangGraph's default reducer for TypedDict fields is replacement, not append.
**How to avoid:** Do NOT write rolling proposals to `trade_proposals` from the rolling node. Instead, write them to `rolling_decisions` (already exists in PipelineState). Then have the downstream node that needs them (risk_node or a merge step) combine both lists.
**Warning signs:** Rolling proposals disappear after strategist runs; only scanner-driven proposals reach the executor.

### Pitfall 2: ExpirationMonitor Needs IB Connection for evaluate_rolling
**What goes wrong:** `evaluate_rolling()` is a sync method (not async) but receives RollingCandidate objects. The rolling node needs to deserialize `state["rolling_candidates"]` (which are plain dicts) back into RollingCandidate Pydantic models before calling `evaluate_rolling()`.
**Why it happens:** Pipeline state stores dicts (JSON-serializable), but `evaluate_rolling()` expects typed Pydantic models.
**How to avoid:** In the rolling node, deserialize: `candidates = [RollingCandidate(**d) for d in state.get("rolling_candidates", [])]`. Note: `evaluate_rolling()` does NOT need the IB connection (it operates on the candidate data alone). Only `scan_expiring_positions()` needs IB.
**Warning signs:** TypeError about dict not having `.unrealized_pnl` attribute.

### Pitfall 3: Rolling Node Needs ExpirationMonitor Instance
**What goes wrong:** The rolling node needs to call `ExpirationMonitor.evaluate_rolling()` and `build_roll_proposals()`, which are instance methods. But the ExpirationMonitor is stored in `deps.expiration_monitor` and may be None.
**Why it happens:** ExpirationMonitor requires an IB connection and is only created in `connect_ib()`.
**How to avoid:** Two approaches: (a) Make `evaluate_rolling()` and `build_roll_proposals()` work without IB (they already do -- they only use `self._config` and the candidates passed in), OR (b) check `deps.expiration_monitor is not None` in the rolling node and skip if unavailable. Approach (b) is simpler and consistent with how `_regime_node` handles missing `deps.regime_detector`. However, since `evaluate_rolling` and `build_roll_proposals` only need the config (not IB), an alternative is to call them as static-like methods or construct a lightweight ExpirationMonitor with a dummy IB just for the config access.
**Recommended:** Check `deps.expiration_monitor is not None`. If None, return empty rolling_decisions. This is the safest and most consistent approach.

### Pitfall 4: Two Different trade_rejected Payload Shapes
**What goes wrong:** The Slack handler assumes a single payload format but there are two publishers.
**Why it happens:** Executor rejections have `{symbol, reason, status, run_id}`. Approval rejections have `{approval_id, reason, symbols, run_id}`.
**How to avoid:** Use defensive `data.get()` with sensible defaults in the Slack handler. Check for both `symbol` (singular, from executor) and `symbols` (plural list, from approval). Display whichever is available.
**Warning signs:** KeyError or missing fields in Slack messages for one rejection type but not the other.

### Pitfall 5: Rolling Proposals Must Have Unique proposal_id
**What goes wrong:** The executor and risk manager cross-reference proposals by `proposal_id`. Rolling proposals from `build_roll_proposals()` do not have a `proposal_id` field.
**Why it happens:** The rolling proposal format was designed before integration with the full pipeline was considered.
**How to avoid:** Generate a `proposal_id` in the rolling node when converting proposals to StrategyProposal format. Use a deterministic format like `roll-{con_id}-{run_id}` for traceability.
**Warning signs:** Risk assessments cannot find matching proposals; executor skips rolling trades.

## Code Examples

### Rolling Node Implementation Pattern
```python
# Source: Follows existing _regime_node pattern in pipeline.py
async def _rolling_node(state: PipelineState, deps: PipelineDeps) -> dict:
    """Evaluate rolling candidates and produce rolling decisions."""
    run_id = state.get("run_id", "")
    candidates_raw = state.get("rolling_candidates", [])

    if not candidates_raw or deps.expiration_monitor is None:
        return {"rolling_decisions": []}

    try:
        # Deserialize from pipeline state dicts back to typed models
        candidates = [RollingCandidate(**d) for d in candidates_raw]

        # Evaluate: deterministic decision logic (no LLM)
        decisions = deps.expiration_monitor.evaluate_rolling(candidates)

        # Build close/open proposals
        proposals = deps.expiration_monitor.build_roll_proposals(decisions)

        # Log decision
        await log_agent_decision(
            session_factory=deps.session_factory,
            run_id=run_id,
            agent_name="rolling_monitor",
            output=...,  # summary of decisions
            duration_ms=...,
            input_summary=f"{len(candidates)} rolling candidates",
        )

        return {
            "rolling_decisions": [d.model_dump() for d in decisions],
        }
    except Exception as exc:
        log.error("pipeline.rolling_node.error", error=str(exc), exc_info=True)
        return {"rolling_decisions": []}
```

### Risk Node Rolling Integration Pattern
```python
# In _risk_node, after processing strategist trade_proposals:
# Also process rolling decisions that need risk validation
rolling_decisions = state.get("rolling_decisions", [])
for decision in rolling_decisions:
    if decision.get("action") in ("roll", "close"):
        # Convert to TradeProposal format and evaluate through risk gate
        # ... (format conversion logic)
```

### SlackNotifier trade_rejected Handler Pattern
```python
# Source: Follows existing _blocks_trade_executed pattern in slack.py
def _blocks_trade_rejected(self, data: dict) -> list[dict]:
    """Build blocks for a trade rejection alert."""
    # Handle both executor and approval rejection payloads
    symbol = data.get("symbol", "")
    symbols = data.get("symbols", [])
    display_symbol = symbol or (", ".join(symbols) if symbols else "?")
    reason = data.get("reason", "unknown")
    status = data.get("status", "")
    approval_id = data.get("approval_id", "")

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Trade Rejected",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Symbol:* {display_symbol}"},
                {"type": "mrkdwn", "text": f"*Reason:* {reason}"},
            ],
        },
    ]
    # Add status/approval_id if present
    ...
    return blocks
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Rolling candidates scanned but unused | Rolling candidates -> evaluate -> propose -> risk -> execute | Phase 10 | Closes AGENT-08 requirement |
| trade_rejected falls back to generic JSON block | Dedicated Block Kit handler with header + fields | Phase 10 | Consistent UX across all 7 alert channels |

**No deprecated/outdated items** -- all libraries are already installed and current.

## Open Questions

1. **Rolling proposals bypassing strategist vs going through it**
   - What we know: Prior decision [06-02] mandates deterministic rolling (no LLM). The strategist is an LLM agent. Rolling proposals should NOT go through the LLM strategist.
   - What's unclear: The exact mechanism for merging rolling proposals with scanner-driven proposals for the risk gate. Option C (risk node reads rolling_decisions directly) avoids the merge problem.
   - Recommendation: Use Option C. Rolling node writes to `rolling_decisions`. Risk node processes both `trade_proposals` (from strategist) and `rolling_decisions` (from rolling node). Executor similarly processes both. This keeps the rolling path fully deterministic.

2. **Rolling proposals format for executor**
   - What we know: The executor expects risk-approved assessments cross-referenced with trade_proposals. Rolling proposals have a different shape than StrategyProposal.
   - What's unclear: Whether to convert rolling proposals to full StrategyProposal format or create a parallel execution path in the executor.
   - Recommendation: Convert rolling proposals to StrategyProposal-compatible dicts in the rolling node. Each roll has one or two legs (close leg, and optionally an open leg). Set `strategy_type` to "roll_close" or "roll_open" so the executor can distinguish them in logs. This reuses the entire existing risk + execution path with zero changes to those nodes.

3. **State schema change implications**
   - What we know: PipelineState already has `rolling_candidates` and `rolling_decisions` fields. No new fields are strictly needed if using Option C.
   - What's unclear: Whether adding `rolling_proposals` (converted StrategyProposal-compatible dicts) as a new PipelineState field would be cleaner.
   - Recommendation: Avoid adding new PipelineState fields. Use `rolling_decisions` to carry both the decision metadata and the converted proposals. Or have the rolling node write converted proposals directly into `trade_proposals` with LangGraph Annotated reducer. Simplest: have the risk node merge them internally.

## Sources

### Primary (HIGH confidence)
- Codebase inspection: `src/trading/agents/rolling.py` -- ExpirationMonitor with evaluate_rolling() and build_roll_proposals() fully implemented
- Codebase inspection: `src/trading/agents/pipeline.py` -- 6 existing pipeline nodes, StateGraph topology, PipelineDeps
- Codebase inspection: `src/trading/agents/state.py` -- PipelineState TypedDict with rolling_candidates and rolling_decisions
- Codebase inspection: `src/trading/app.py` -- run_agent_pipeline() already calls scan_expiring_positions() and passes rolling_candidates
- Codebase inspection: `src/trading/alerts/slack.py` -- SlackNotifier with 6 of 7 channel handlers (trade_rejected missing)
- Codebase inspection: `src/trading/alerts/router.py` -- AlertRouter subscribes to all 7 channels including trade_rejected
- Codebase inspection: `tests/test_alert_router.py` -- Test patterns for Slack Block Kit assertions
- Codebase inspection: `tests/test_agents.py` -- Test patterns for rolling models, ExpirationMonitor, pipeline integration

### Secondary (MEDIUM confidence)
- Prior planning docs: `.planning/phases/06-advanced-agent-intelligence/06-02-PLAN.md` -- Rolling design decisions
- Prior planning docs: `.planning/phases/06-advanced-agent-intelligence/06-03-PLAN.md` -- Pipeline integration decisions
- Milestone audit: `.planning/v1-MILESTONE-AUDIT.md` -- Gap identification and tech debt catalog

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already installed and in use; no new dependencies
- Architecture: HIGH -- all infrastructure exists; this is pure wiring and format conversion
- Pitfalls: HIGH -- identified from direct codebase inspection (LangGraph state semantics, payload shapes, deserialization needs)

**Research date:** 2026-04-05
**Valid until:** 2026-05-05 (stable -- no external dependencies to change)
