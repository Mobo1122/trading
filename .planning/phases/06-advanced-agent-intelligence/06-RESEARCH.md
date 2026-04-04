# Phase 6: Advanced Agent Intelligence - Research

**Researched:** 2026-04-04
**Domain:** Market regime detection and automated options position rolling within LLM agent pipeline
**Confidence:** MEDIUM (regime detection patterns are well-established; rolling logic is domain-specific and requires careful integration with existing pipeline)

## Summary

Phase 6 adds two capabilities to the existing Phase 5 LangGraph agent pipeline: (1) market regime detection that classifies conditions as bull, bear, sideways, or volatile and adapts the strategy mix the strategist agent uses, and (2) automated position rolling that monitors expiring positions and rolls them to new expirations when appropriate. Both capabilities must integrate with the existing `PipelineState`, `PipelineDeps`, and agent logging infrastructure.

The recommended approach for regime detection is a deterministic, rules-based model using indicators already available in the codebase (IV rank/percentile from IVEngine, VIX proxy via market data, price momentum from stored quotes) rather than a machine learning approach (HMM). The ML approach (hmmlearn) adds a training dependency, requires historical training data, and introduces stochastic behavior that conflicts with the project's "deterministic safety first" philosophy. A rules-based regime detector is testable, explainable, and auditable -- all critical for a system that trades real money. The LLM scanner agent can then interpret the regime classification and adjust its opportunity identification accordingly.

For position rolling, the system needs to query IB for current positions via `ib.positions()`, identify options positions approaching expiration (configurable DTE threshold, default 7 days), evaluate whether rolling is appropriate (based on P&L, delta status, regime context), and execute the roll as a close-then-open sequence through the existing execution pipeline. Rolling decisions must pass through the same risk gate as new trades. A dedicated "roller" agent or a pre-pipeline check that feeds rolling candidates into the pipeline are both viable; the pre-pipeline check approach is recommended as it avoids a new LLM agent and keeps rolling deterministic with LLM override capability.

**Primary recommendation:** Build regime detection as a deterministic rules-based module (not ML), inject regime context into the scanner prompt, and implement rolling as a periodic expiration monitor that feeds candidates back through the existing pipeline for execution.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| (no new libraries) | - | Phase 6 uses existing stack | All capabilities build on Phase 1-5 infrastructure |
| ib_async | >=2.1.0 | Position retrieval via `ib.positions()` | Already installed; provides `Position` objects with contract expiry data |
| pydantic | >=2.12.5 | Regime and rolling output models | Already installed; consistent with all existing agent models |
| pydantic-ai-slim[anthropic] | >=1.77.0 | Enhanced scanner agent with regime context | Already installed; scanner agent just needs prompt extension |
| langgraph | >=1.1.6 | Pipeline state extension for regime data | Already installed; PipelineState TypedDict extended with new fields |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| numpy | (already transitive dep) | Moving average / momentum calculations | Regime detection indicator computations |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Rules-based regime detection | hmmlearn HMM | HMM adds training requirement, stochastic output, harder to test/audit; rules are deterministic and explainable |
| Pre-pipeline rolling check | Dedicated "roller" PydanticAI agent | Extra LLM calls per cycle; rolling criteria are mostly deterministic (DTE, P&L thresholds); LLM adds cost without proportional value |
| Extending existing scanner with regime | Separate regime agent node | Adding a new node increases pipeline complexity; regime is an input TO scanning, not a separate stage |

**Installation:**
```bash
# No new dependencies needed -- Phase 6 uses existing stack entirely
```

## Architecture Patterns

### Recommended Project Structure
```
src/trading/
    agents/
        __init__.py           # Updated exports
        config.py             # Extended with regime + rolling config
        models.py             # Extended with RegimeClassification, RollingCandidate, RollingDecision
        state.py              # Extended PipelineState with regime fields
        scanner.py            # Enhanced with regime-aware scanning
        strategist.py         # Enhanced with regime-aware strategy selection
        pipeline.py           # Extended with regime detection pre-step and rolling integration
        logging.py            # Extended STAGE_ORDER with new agent names
        regime.py             # NEW: Deterministic regime detection module
        rolling.py            # NEW: Expiration monitor and rolling logic
        ...                   # Existing files unchanged
```

### Pattern 1: Deterministic Regime Detection Module
**What:** A pure Python module (no LLM) that classifies the current market regime based on quantitative indicators. The classification is injected into the pipeline state before the scanner runs, so the scanner prompt includes regime context.
**When to use:** Every pipeline run, as the first step before scanner.
**Rationale:** Regime detection uses quantitative indicators (IV levels, price momentum, VIX proxy) that are better handled deterministically than by LLM. The LLM's value-add is in interpreting regime context for opportunity selection, not in computing the regime itself.

**Example:**
```python
# src/trading/agents/regime.py
from enum import Enum
from pydantic import BaseModel, Field
from trading.market_data.models import IVData

class MarketRegime(str, Enum):
    """Market regime classifications."""
    BULL_QUIET = "bull_quiet"       # Uptrend + low volatility
    BULL_VOLATILE = "bull_volatile" # Uptrend + high volatility
    BEAR_QUIET = "bear_quiet"       # Downtrend + low volatility
    BEAR_VOLATILE = "bear_volatile" # Downtrend + high volatility
    SIDEWAYS = "sideways"           # Range-bound
    UNKNOWN = "unknown"             # Insufficient data

class RegimeClassification(BaseModel):
    """Result of regime detection with full reasoning."""
    regime: MarketRegime
    confidence: float = Field(ge=0, le=1)
    trend_signal: str       # e.g. "bullish", "bearish", "neutral"
    volatility_signal: str  # e.g. "high", "low", "normal"
    indicators: dict        # Raw indicator values for audit
    reasoning: str          # Human-readable explanation

# Strategy mix mapping by regime
REGIME_STRATEGY_WEIGHTS: dict[MarketRegime, dict[str, float]] = {
    MarketRegime.BULL_QUIET: {
        "covered_call": 0.3,
        "cash_secured_put": 0.3,
        "vertical_spread": 0.2,   # bull call spreads
        "iron_condor": 0.2,
    },
    MarketRegime.BEAR_VOLATILE: {
        "vertical_spread": 0.4,   # bear put spreads
        "iron_condor": 0.1,       # tight wings
        "cash_secured_put": 0.0,  # too risky
        "covered_call": 0.5,      # defensive income
    },
    MarketRegime.SIDEWAYS: {
        "iron_condor": 0.4,       # range-bound profit
        "covered_call": 0.2,
        "cash_secured_put": 0.2,
        "calendar_spread": 0.2,
    },
    # ... other regimes
}

class RegimeDetector:
    """Deterministic market regime classifier."""

    def __init__(self, settings):
        self._settings = settings

    async def detect(
        self,
        iv_data: dict[str, IVData],
        price_data: dict[str, dict],
        vix_data: dict | None = None,
    ) -> RegimeClassification:
        """Classify current market regime from indicators.

        Indicator composition:
        1. Trend: SMA crossover (price vs 50-day SMA proxy from stored quotes)
        2. Volatility: Average IV rank across watchlist (from IVEngine)
        3. VIX level: If VIX/proxy available, >25 = high vol, <15 = low vol
        """
        # Compute trend signal from price momentum
        trend = self._compute_trend(price_data)
        # Compute volatility signal from IV rank average
        vol = self._compute_volatility(iv_data)
        # Combine into regime
        regime = self._classify(trend, vol, vix_data)
        ...
```

### Pattern 2: Regime-Aware Scanner Prompt Injection
**What:** The scanner agent's run prompt is dynamically extended with regime context, influencing what opportunities the LLM identifies. The regime classification and strategy weights are prepended to the scanner instructions.
**When to use:** Every scanner invocation.
**Rationale:** Rather than hard-coding regime logic in the scanner, the LLM interprets regime context naturally in its opportunity identification. This keeps the scanner agent flexible while ensuring regime awareness.

**Example:**
```python
# In pipeline.py, before calling run_scanner:
regime = state.get("regime_classification", {})
regime_name = regime.get("regime", "unknown")
strategy_weights = REGIME_STRATEGY_WEIGHTS.get(regime_name, {})

regime_context = (
    f"CURRENT MARKET REGIME: {regime_name}\n"
    f"Regime confidence: {regime.get('confidence', 0):.0%}\n"
    f"Trend: {regime.get('trend_signal', 'unknown')}, "
    f"Volatility: {regime.get('volatility_signal', 'unknown')}\n"
    f"Preferred strategy mix: {strategy_weights}\n"
    f"Adapt your opportunity scanning to favor strategies that "
    f"perform well in this regime."
)
# Prepend to scanner prompt
```

### Pattern 3: Position Expiration Monitor (Rolling Logic)
**What:** A periodic check that queries IB for current positions via `ib.positions()`, filters options positions approaching expiration (DTE <= threshold), evaluates rolling criteria, and generates `RollingCandidate` objects that are either auto-rolled or fed to the pipeline for execution.
**When to use:** On a configurable schedule (e.g., daily at market open, or before each pipeline run).
**Rationale:** Rolling is primarily a deterministic check (DTE threshold, P&L status, delta proximity to strike) with optional LLM judgment for edge cases. Keeping it separate from the main scanner->strategist flow avoids conflating new opportunity identification with position management.

**Example:**
```python
# src/trading/agents/rolling.py
from datetime import date, datetime
from pydantic import BaseModel, Field
from ib_async import Position

class RollingCandidate(BaseModel):
    """A position identified for potential rolling."""
    symbol: str
    con_id: int
    current_expiry: str           # YYYYMMDD
    days_to_expiry: int
    position_size: float
    avg_cost: float
    current_value: float | None
    unrealized_pnl: float | None
    strategy_type: str | None     # From original trade
    rolling_reason: str           # "approaching_expiry", "itm_risk", etc.

class RollingDecision(BaseModel):
    """Decision on whether and how to roll a position."""
    candidate: RollingCandidate
    should_roll: bool
    target_expiry: str | None     # New expiry if rolling
    target_strike: float | None   # New strike if adjusting
    reasoning: str
    estimated_credit_debit: float | None

class ExpirationMonitor:
    """Monitors positions for expiration and generates rolling candidates."""

    def __init__(self, ib, settings, session_factory):
        self._ib = ib
        self._settings = settings
        self._session_factory = session_factory

    async def scan_expiring_positions(
        self,
        dte_threshold: int = 7,
    ) -> list[RollingCandidate]:
        """Query IB for options positions within DTE threshold."""
        positions = self._ib.positions()
        candidates = []
        today = date.today()

        for pos in positions:
            contract = pos.contract
            if contract.secType != "OPT":
                continue
            if not contract.lastTradeDateOrContractMonth:
                continue

            expiry_str = contract.lastTradeDateOrContractMonth
            expiry_date = datetime.strptime(expiry_str, "%Y%m%d").date()
            dte = (expiry_date - today).days

            if dte <= dte_threshold:
                candidates.append(RollingCandidate(
                    symbol=contract.symbol,
                    con_id=contract.conId,
                    current_expiry=expiry_str,
                    days_to_expiry=dte,
                    position_size=float(pos.position),
                    avg_cost=float(pos.avgCost),
                    current_value=None,  # Populated from portfolio()
                    unrealized_pnl=None,
                    strategy_type=None,
                    rolling_reason="approaching_expiry",
                ))

        return candidates
```

### Pattern 4: Rolling Execution Through Existing Pipeline
**What:** Rolling decisions are executed by constructing close + open proposals that flow through the existing risk gate and execution service. A roll is two trades: close the expiring position, then open a new position at a later expiration.
**When to use:** When the rolling logic decides a position should be rolled.
**Rationale:** Reusing the existing execution pipeline maintains the safety guarantee that every trade passes through the deterministic risk gate. No bypassing the risk manager for rolling.

**Example:**
```python
# Rolling a short put: close current, open new at later expiry
close_proposal = TradeProposal(
    legs=[TradeLeg(
        symbol="SPY", sec_type="OPT", action="BUY",  # Close short
        quantity=1, right="P", strike=420.0, expiry="20260410",
    )],
    estimated_greeks=GreeksImpact(...),
    max_loss=0.0,  # Closing position
    strategy_type="roll_close",
    account_value=100000.0,
)

open_proposal = TradeProposal(
    legs=[TradeLeg(
        symbol="SPY", sec_type="OPT", action="SELL",  # Open new short
        quantity=1, right="P", strike=420.0, expiry="20260417",
    )],
    estimated_greeks=GreeksImpact(...),
    max_loss=42000.0,
    strategy_type="roll_open",
    account_value=100000.0,
)

# Both pass through risk gate
close_decision = await execution_service.submit_order(close_proposal)
if close_decision.approved:
    open_decision = await execution_service.submit_order(open_proposal)
```

### Pattern 5: Extended PipelineState for Regime Context
**What:** Add regime classification fields to the existing LangGraph `PipelineState` TypedDict so regime data flows through the graph.
**When to use:** Pipeline state definition.
**Rationale:** Keeping regime data in the pipeline state makes it available to all downstream agents via the state dict, and it gets checkpointed automatically by LangGraph.

**Example:**
```python
# Extended PipelineState
class PipelineState(TypedDict):
    # ... existing fields ...
    watchlist: list[str]
    opportunities: list[dict]
    trade_proposals: list[dict]
    risk_assessments: list[dict]
    execution_results: list[dict]
    scanner_reasoning: str
    strategist_reasoning: str
    risk_reasoning: str
    executor_reasoning: str
    run_id: str
    aborted_at: str
    # Phase 6 additions:
    regime_classification: dict   # Serialized RegimeClassification
    rolling_candidates: list[dict]  # Serialized RollingCandidate list
    rolling_decisions: list[dict]   # Serialized RollingDecision list
```

### Anti-Patterns to Avoid
- **Using ML for regime detection in a real-money trading system without extensive backtesting:** HMM/GMM models can misclassify regimes during regime transitions, leading to wrong strategy selection. Start with deterministic rules that are testable and interpretable.
- **Making rolling decisions purely with LLM:** Rolling criteria (DTE, P&L, delta proximity) are quantitative and should be computed deterministically. The LLM adds value for edge cases but should not be the primary decision maker.
- **Bypassing risk gate for rolling:** Rolling trades are real trades that affect portfolio risk. They MUST go through the same risk validation as new trades.
- **Over-engineering regime classification:** Four-to-five regimes is sufficient. More granular classification adds complexity without proportional benefit for options strategy selection.
- **Treating rolling as a new pipeline stage:** Rolling is position management, not opportunity discovery. It should run as a separate schedule (or pre-pipeline check), not as an additional node in the scanner->strategist->risk->executor pipeline.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Position retrieval | Custom DB position tracker | `ib.positions()` and `ib.portfolio()` | IB is the authoritative source for current positions; DB may be stale |
| DTE calculation | Custom date arithmetic | `datetime.strptime(expiry, "%Y%m%d").date() - date.today()` | Standard library is sufficient; avoid timezone bugs |
| Strategy execution for rolls | Custom IB order placement | Existing `OrderExecutionService.submit_order()` | Maintains risk gate, order tracking, and fill recording |
| Regime change logging | Custom log table | Existing `AgentDecisionLog` table with regime-specific agent_name | Reuses the audit infrastructure from Phase 5 |
| Pipeline state extension | New state management | LangGraph `PipelineState` TypedDict extension | Checkpointing and state flow handled automatically |

**Key insight:** Phase 6 is primarily about intelligence logic, not infrastructure. All the heavy lifting (execution, risk, logging, state management) is already built in Phases 1-5. The new code should be thin modules that produce decisions and feed them through existing infrastructure.

## Common Pitfalls

### Pitfall 1: Regime Whiplash (Frequent Regime Changes)
**What goes wrong:** The regime detector oscillates rapidly between classifications (e.g., bull -> sideways -> bull every pipeline run), causing the strategy mix to constantly change and generating contradictory trades.
**Why it happens:** Indicator values near classification boundaries cause flip-flopping. Markets often spend time near boundary conditions.
**How to avoid:** Add hysteresis to regime transitions. Require a regime to persist for N consecutive checks (e.g., 3 pipeline runs) before switching. Alternatively, use a "confidence decay" where the current regime has a bias toward persistence.
**Warning signs:** Agent decision logs showing regime changes every pipeline run. Contradictory strategies proposed in consecutive runs.

### Pitfall 2: Rolling Into Worse Positions
**What goes wrong:** The system automatically rolls positions to new expirations even when the trade thesis is invalidated, compounding losses by paying additional debit for rolling.
**Why it happens:** Naive DTE-based rolling that always rolls without evaluating whether the original trade thesis still holds. Rolling a losing position just extends the loss.
**How to avoid:** Include P&L check in rolling criteria. If unrealized loss exceeds a threshold (e.g., 2x original credit received), do NOT roll -- close and take the loss. Also check if the regime has changed since the original trade was opened; a regime change may invalidate the trade thesis.
**Warning signs:** Multiple consecutive rolls on the same symbol/position. Rolling positions with significant unrealized losses.

### Pitfall 3: Position Data Staleness from IB
**What goes wrong:** `ib.positions()` returns stale data if IB connection was recently restored or if the account hasn't been fully synced.
**Why it happens:** IB sends position data asynchronously after connection. Calling `positions()` immediately after reconnect may return incomplete data.
**How to avoid:** Ensure position data is fresh by checking `ib.accountValues()` timestamp or using `ib.reqPositions()` to force a refresh. Add a staleness check (skip rolling if position data is older than 5 minutes).
**Warning signs:** Rolling monitor reporting zero positions when positions are known to exist.

### Pitfall 4: Regime Detection Based on Insufficient Data
**What goes wrong:** On cold start or with a new symbol, the regime detector has insufficient price/IV history to make a meaningful classification.
**Why it happens:** IVEngine requires >=20 data points for IV rank calculation. Price momentum requires sufficient historical quotes.
**How to avoid:** The regime detector must handle `None`/insufficient data gracefully by returning `MarketRegime.UNKNOWN` with low confidence. The scanner should operate normally (without regime bias) when regime is UNKNOWN.
**Warning signs:** Regime always classified as UNKNOWN. Regime confidence consistently below 0.3.

### Pitfall 5: Rolling Multi-Leg Positions (Spreads, Condors)
**What goes wrong:** Rolling an iron condor requires closing all 4 legs and opening 4 new legs. If only some legs are closed, the position becomes unhedged.
**Why it happens:** Treating multi-leg positions as independent single-leg options and rolling them individually.
**How to avoid:** Track positions at the strategy level, not individual leg level. When rolling a spread or condor, close ALL legs as a combo order and open ALL new legs as a combo order. Use the existing `ComboOrderBuilder` from Phase 4 for multi-leg orders.
**Warning signs:** Orphaned single-leg positions appearing after rolling. Net portfolio exposure changing unexpectedly after a roll.

### Pitfall 6: VIX Data Availability
**What goes wrong:** The regime detector expects VIX data, but VIX may not be in the watchlist or subscribed for market data.
**Why it happens:** VIX (CBOE Volatility Index) requires a separate subscription and has a different security type (IND) than typical equities/options.
**How to avoid:** Add "VIX" to the watchlist or use a proxy (e.g., average IV rank across the watchlist symbols, or SPY's implied volatility). The IV rank/percentile data from IVEngine already provides a volatility signal. Design the regime detector to work WITHOUT VIX, using VIX as an optional enhancement.
**Warning signs:** Regime detector always falling back to non-VIX path.

## Code Examples

Verified patterns from official sources and existing codebase:

### Retrieving IB Positions for Rolling
```python
# Source: ib_async API docs (https://ib-api-reloaded.github.io/ib_async/api.html)
# Position object has: account, contract, position, avgCost
# Contract for options includes: lastTradeDateOrContractMonth, strike, right, symbol

positions = ib.positions()
for pos in positions:
    contract = pos.contract
    if contract.secType == "OPT":
        expiry = contract.lastTradeDateOrContractMonth  # "20260417" format
        symbol = contract.symbol
        strike = contract.strike
        right = contract.right  # "C" or "P"
        qty = pos.position  # Positive = long, negative = short
        avg_cost = pos.avgCost

# For unrealized P&L, use portfolio():
portfolio = ib.portfolio()
for item in portfolio:
    unrealized_pnl = item.unrealizedPNL
    market_value = item.marketValue
```

### Regime Detection Indicator Computation
```python
# Compute trend from stored market quote history (Phase 2 market_quotes table)
# Using existing SQLAlchemy async queries
import numpy as np
from sqlalchemy import select, func
from trading.db.models import MarketQuote

async def compute_price_momentum(
    session_factory, symbol: str, lookback_days: int = 20
) -> float | None:
    """Compute price momentum as % change over lookback period.

    Returns positive for uptrend, negative for downtrend, near-zero for sideways.
    """
    async with get_session(session_factory) as session:
        result = await session.execute(
            select(MarketQuote.last)
            .where(MarketQuote.symbol == symbol)
            .order_by(MarketQuote.timestamp.desc())
            .limit(lookback_days)
        )
        prices = [row[0] for row in result.all() if row[0] is not None]

    if len(prices) < 2:
        return None

    # Momentum = (newest - oldest) / oldest
    return (prices[0] - prices[-1]) / prices[-1]
```

### Adding Regime Node to LangGraph Pipeline
```python
# Source: Existing pipeline.py pattern (Phase 5)
# Regime detection is a synchronous pre-step, not an LLM agent call

async def _regime_node(state: PipelineState, deps: PipelineDeps) -> dict:
    """Detect market regime and inject into pipeline state.

    This node runs BEFORE the scanner. It computes regime classification
    from quantitative indicators and stores it in the pipeline state
    so downstream agents have regime context.
    """
    try:
        # Batch compute IV for watchlist symbols
        iv_batch = await deps.iv_engine.compute_batch(state["watchlist"])

        # Get latest price data from Redis
        price_data = {}
        for symbol in state["watchlist"]:
            data = await deps.redis_client.hgetall(f"market_data:{symbol}")
            if data:
                price_data[symbol] = data

        # Detect regime
        detector = RegimeDetector(deps.settings)
        classification = await detector.detect(iv_batch, price_data)

        await log_agent_decision(
            session_factory=deps.session_factory,
            run_id=state.get("run_id", ""),
            agent_name="regime_detector",
            output=classification,
            duration_ms=0,
            input_summary=f"{len(state['watchlist'])} symbols",
        )

        return {
            "regime_classification": classification.model_dump(),
        }
    except Exception as exc:
        return {
            "regime_classification": RegimeClassification(
                regime=MarketRegime.UNKNOWN,
                confidence=0.0,
                trend_signal="unknown",
                volatility_signal="unknown",
                indicators={},
                reasoning=f"Regime detection failed: {exc}",
            ).model_dump(),
        }


# Updated pipeline topology:
# START -> regime_detector -> scanner -> [conditional] -> strategist -> ...
workflow.add_node("regime_detector", lambda s: _regime_node(s, deps))
workflow.add_node("scanner", lambda s: _scan_node(s, deps))
workflow.add_edge(START, "regime_detector")
workflow.add_edge("regime_detector", "scanner")
# ... rest unchanged
```

### Rolling Configuration
```python
# Extension to AgentConfig in src/trading/agents/config.py
class RollingConfig(BaseModel):
    """Configuration for automated position rolling."""
    enabled: bool = True
    dte_threshold: int = Field(default=7, ge=1, le=30,
        description="Roll positions with DTE <= this value")
    max_loss_multiple: float = Field(default=2.0, gt=0,
        description="Don't roll if unrealized loss > this * original credit")
    check_interval_minutes: int = Field(default=60, ge=5,
        description="How often to check for expiring positions")
    preferred_roll_dte: int = Field(default=30, ge=7,
        description="Target DTE for the new position after rolling")
    allow_strike_adjustment: bool = Field(default=True,
        description="Allow rolling to a different strike (up/down)")

class RegimeConfig(BaseModel):
    """Configuration for market regime detection."""
    enabled: bool = True
    hysteresis_count: int = Field(default=3, ge=1,
        description="Regime must persist N checks before switching")
    iv_rank_high_threshold: float = Field(default=60.0,
        description="IV rank above this = high volatility signal")
    iv_rank_low_threshold: float = Field(default=30.0,
        description="IV rank below this = low volatility signal")
    momentum_bull_threshold: float = Field(default=0.02,
        description="Price momentum > this = bullish trend signal")
    momentum_bear_threshold: float = Field(default=-0.02,
        description="Price momentum < this = bearish trend signal")
    vix_high_threshold: float = Field(default=25.0,
        description="VIX above this = high volatility (if VIX available)")
    vix_low_threshold: float = Field(default=15.0,
        description="VIX below this = low volatility (if VIX available)")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| HMM-only regime detection | Hybrid: deterministic rules + optional ML overlay | 2024-2025 | Rules provide explainability; ML can be added as enhancement |
| Manual position rolling | Systematic rules-based with human override | 2025-2026 | Automated rolling with DTE/P&L thresholds is standard at prop trading firms |
| Separate regime detection service | Inline pre-pipeline step | 2025 (LangGraph maturity) | LangGraph nodes make it natural to add pre-steps to existing pipelines |
| VIX-only volatility measure | Multi-indicator (IV rank + VIX + price vol) | Always | Single-indicator regime detection is fragile; combining improves robustness |

**Deprecated/outdated:**
- Pure VIX-threshold regime detection (VIX > 20 = bear, etc.): Oversimplified; VIX can be elevated in bull markets during corrections. Multi-indicator approach is required.

## Open Questions

Things that couldn't be fully resolved:

1. **Multi-leg position grouping for rolling**
   - What we know: IB's `positions()` returns individual contracts, not grouped strategies. An iron condor appears as 4 separate option positions.
   - What's unclear: How to reliably group individual positions back into their original multi-leg strategy. The `proposal_id` in the Order table links to the original strategy, but mapping from IB position data back to proposal requires con_id matching.
   - Recommendation: In plan 06-02, implement a `PositionGrouper` that matches IB positions back to original orders via con_id/proposal_id linkage in the orders table. For the initial implementation, focus on single-leg rolling (individual options) and defer multi-leg rolling to a follow-up enhancement.

2. **Historical price data availability for momentum**
   - What we know: Phase 2 stores `market_quotes` in TimescaleDB with bid/ask/last, but the amount of historical data depends on how long the system has been running.
   - What's unclear: Whether sufficient history (20+ days) exists for meaningful momentum calculation on a recently-deployed system.
   - Recommendation: Gracefully handle insufficient history by returning `MarketRegime.UNKNOWN`. As a fallback, compute momentum from IV history data (which bootstraps 252 trading days in Phase 2).

3. **VIX subscription feasibility**
   - What we know: VIX is an index (CBOE:VIX), not a stock. ib_async can subscribe to it as `Index("VIX", "CBOE")`. IB market data subscriptions have limits (100 lines in the current config).
   - What's unclear: Whether VIX data requires a separate market data subscription line or comes free with certain IB subscription bundles.
   - Recommendation: Design regime detection to work WITHOUT VIX (using IV rank average as proxy). Add VIX as an optional enhancement via config. Include "VIX" in the watchlist only if explicitly configured.

4. **Rolling frequency and market hours**
   - What we know: Options can be rolled during market hours when liquidity is available. Rolling near market close on expiration day is risky due to widening spreads.
   - What's unclear: The optimal schedule for the rolling check (once daily at market open? every pipeline cycle? only on expiration day?).
   - Recommendation: Default to checking once daily during morning hours (10:00 AM ET), configurable via `RollingConfig.check_interval_minutes`. Avoid rolling in the last hour of trading on expiration day.

## Sources

### Primary (HIGH confidence)
- Existing codebase (Phase 5): `src/trading/agents/` -- Pipeline architecture, state management, agent patterns
- [ib_async API docs](https://ib-api-reloaded.github.io/ib_async/api.html) -- `positions()`, `portfolio()`, `Position`, `PortfolioItem` APIs
- Existing codebase (Phase 2): `src/trading/analytics/iv_engine.py` -- IVEngine with IV rank/percentile computation
- Existing codebase (Phase 3): `src/trading/risk/manager.py` -- RiskManager.check_trade() for risk validation of rolling trades

### Secondary (MEDIUM confidence)
- [QuantStart: Market Regime Detection using HMMs](https://www.quantstart.com/articles/market-regime-detection-using-hidden-markov-models-in-qstrader/) -- HMM approach details, feature engineering patterns
- [Data Driven Options: Rolling Iron Condors](https://datadrivenoptions.com/rolling-iron-condors/) -- Quantitative rolling rules: DTE thresholds, delta zones, premium targets
- [Option Alpha: Rolling Options Guide](https://optionalpha.com/learn/rolling-options) -- General rolling principles and when to roll vs let expire
- [Blank Capital Research: Market Regimes Guide](https://blankcapitalresearch.com/learn/understanding-market-regimes) -- Regime classification framework (bull quiet, bull volatile, bear quiet, bear volatile)
- [LangGraph docs](https://docs.langchain.com/oss/python/langgraph/graph-api) -- Conditional edges, state graph extension patterns

### Tertiary (LOW confidence)
- [Pollenate Trading: Market Regime Strategies](https://www.pollinatetrading.com/blog/market-regime-trading-strategies) -- Strategy selection by regime (needs backtesting validation)
- WebSearch general: Options rolling automation community best practices (unverified quantitative thresholds)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - No new libraries needed; all capabilities build on existing Phase 1-5 infrastructure
- Architecture: MEDIUM - Patterns follow existing codebase conventions but regime detection indicator thresholds need tuning in production
- Pitfalls: HIGH - Most pitfalls identified from existing codebase patterns and options trading domain knowledge
- Rolling logic: MEDIUM - Quantitative thresholds (DTE, P&L multiples) are community consensus but not battle-tested in this specific system
- Regime strategy weights: LOW - Strategy mix percentages per regime are educated estimates; require backtesting/paper trading validation

**Research date:** 2026-04-04
**Valid until:** 30 days (stable domain; indicator thresholds may need tuning based on paper trading results)
