# Phase 3: Risk Engine - Research

**Researched:** 2026-04-03
**Domain:** Deterministic rules-based risk management for options trading
**Confidence:** HIGH

## Summary

The risk engine is a pure deterministic rules gate that evaluates every trade proposal against configurable limits before any order can be submitted. This phase builds on the existing codebase patterns (Pydantic models, async SQLAlchemy, Redis caching, structlog, YAML config) without introducing new major dependencies. The domain is well-understood -- position sizing, Greeks aggregation, circuit breakers, and strategy restrictions are standard algorithmic trading primitives.

The architecture follows a single entry point pattern: a `RiskManager` class with a `check_trade(proposal) -> RiskDecision` method. Each risk rule is a discrete evaluator function that returns pass/fail with details. The manager chains evaluators in order, short-circuiting on first violation. Circuit breaker state lives in Redis for hot-path access and Postgres for crash recovery. Configuration uses the existing YAML-with-Pydantic-validation pattern already established in Phase 1, extended with a `risk_limits` section featuring paper/live separation.

The one external integration is IB's `whatIfOrder` API for pre-trade margin checks. The ib_async library exposes `whatIfOrderAsync()` returning an `OrderState` dataclass with string-typed margin fields (e.g., `initMarginAfter`, `equityWithLoanAfter`). This call must be wrapped with `asyncio.wait_for()` using a 5-second timeout, and timeout is treated as pass-through (non-blocking), not a hard rejection.

**Primary recommendation:** Build the risk engine as a layered evaluator chain with Pydantic models for proposals/decisions, Redis for circuit breaker hot state, Postgres for persistence and audit, and the existing config system for limit management. No new libraries required beyond what is already in the project.

## Standard Stack

The established libraries/tools for this domain:

### Core (already in project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | >=2.12.5 | TradeProposal, RiskDecision, RiskLimits models | Already used for all data models in Phase 1/2; provides Field(gt=0) validation for limits |
| sqlalchemy[asyncio] | >=2.0.48 | RiskDecision audit log, circuit breaker state persistence | Already used for all DB operations; async session pattern established |
| redis[hiredis] | >=7.4.0 | Circuit breaker hot state, loss accumulator cache | Already used with decode_responses=True; HSET/HGET for structured state |
| structlog | >=25.5.0 | Risk evaluation logging with context | Already used everywhere; bind(component="risk_manager") pattern |
| ib_async | >=2.1.0 | whatIfOrder pre-trade margin check | Already used for IB connectivity; whatIfOrderAsync returns OrderState |
| pydantic-settings | >=2.13.1 | Risk limits in Settings with env var override | Already used for layered config |
| pyaml-env | >=1.2.2 | YAML risk limits config with env interpolation | Already used for config loading |
| alembic | >=1.18.4 | Migration for risk_decisions and circuit_breaker_state tables | Already used for schema migrations |

### Supporting (already in project)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tenacity | >=9.1.4 | Retry logic for Redis operations if needed | Non-critical Redis failures |
| fakeredis | >=2.34.1 | Test double for Redis in unit tests | All risk engine unit tests |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Custom evaluator chain | pybreaker for circuit breakers | pybreaker adds complexity; our circuit breaker is domain-specific (loss-based, not failure-based) -- custom is simpler and correct |
| Custom config validation | cerberus or marshmallow | Pydantic already in project; no reason to add another validation library |
| Custom rules engine | python-rules or business-rules | Overkill for 5-6 deterministic rules; simple function chain is clearer and testable |

**Installation:**
```bash
# No new dependencies required. All libraries already in pyproject.toml.
```

## Architecture Patterns

### Recommended Project Structure
```
src/trading/
  risk/
    __init__.py          # Public API: RiskManager, check_trade
    models.py            # TradeProposal, RiskDecision, RiskLimits, ViolatedRule enum
    manager.py           # RiskManager: orchestrates evaluator chain
    evaluators.py        # Individual rule evaluators (pure functions)
    config.py            # RiskLimitsConfig Pydantic model, YAML loading
    circuit_breaker.py   # CircuitBreaker: loss tracking, halt state, Redis/Postgres
    margin_check.py      # whatIfOrder wrapper with timeout
    greeks.py            # Portfolio Greeks aggregation and exposure checking
    repository.py        # DB operations: persist decisions, load/save state
```

### Pattern 1: Evaluator Chain (Core Pattern)
**What:** Each risk rule is a standalone evaluator function: `(proposal, limits, state) -> RiskDecision | None`. Returns None if the rule passes, or a RiskDecision with the violated rule if it fails. The RiskManager iterates evaluators in order and short-circuits on first violation.
**When to use:** Every `check_trade()` invocation.
**Example:**
```python
# Source: Custom architecture aligned with existing codebase patterns
from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime, timezone

class ViolatedRule(str, Enum):
    """Enum of all risk rules that can reject a trade."""
    POSITION_SIZE_DOLLARS = "POSITION_SIZE_DOLLARS"
    POSITION_SIZE_CONTRACTS = "POSITION_SIZE_CONTRACTS"
    POSITION_SIZE_PERCENT = "POSITION_SIZE_PERCENT"
    DELTA_EXPOSURE = "DELTA_EXPOSURE"
    GAMMA_EXPOSURE = "GAMMA_EXPOSURE"
    THETA_EXPOSURE = "THETA_EXPOSURE"
    VEGA_EXPOSURE = "VEGA_EXPOSURE"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    WEEKLY_LOSS_LIMIT = "WEEKLY_LOSS_LIMIT"
    STRATEGY_RESTRICTED = "STRATEGY_RESTRICTED"
    NAKED_OPTION = "NAKED_OPTION"
    MARGIN_INSUFFICIENT = "MARGIN_INSUFFICIENT"
    MARGIN_CHECK_REJECTED = "MARGIN_CHECK_REJECTED"
    RISK_MANAGER_UNAVAILABLE = "RISK_MANAGER_UNAVAILABLE"
    CIRCUIT_BREAKER_ACTIVE = "CIRCUIT_BREAKER_ACTIVE"
    EMERGENCY_HALT = "EMERGENCY_HALT"

class RiskDecision(BaseModel):
    """Result of a risk evaluation."""
    approved: bool
    violated_rule: ViolatedRule | None = None
    details: str = ""
    proposal_id: str = ""
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    margin_result: dict | None = None  # whatIfOrder data if available
    dry_run: bool = False

class TradeProposal(BaseModel):
    """A trade to be evaluated by the risk engine."""
    proposal_id: str
    legs: list[TradeLeg]
    estimated_greeks: GreeksImpact
    max_loss: float  # Caller-computed worst-case loss
    strategy_type: str  # e.g., "covered_call", "naked_put", "iron_condor"
    account_value: float  # Current portfolio value for % calculations

class TradeLeg(BaseModel):
    """Single leg of a trade proposal."""
    symbol: str
    sec_type: str  # STK, OPT, etc.
    action: str  # BUY or SELL
    quantity: int
    contract: object | None = None  # ib_async Contract for whatIfOrder
    order: object | None = None  # ib_async Order for whatIfOrder
```

### Pattern 2: Circuit Breaker with Dual-Storage
**What:** Loss limits are tracked in Redis (HSET/HGET on a hash key like `risk:circuit_breaker:{mode}`) for hot-path reads, and persisted to Postgres for crash recovery. On startup, Postgres state is loaded into Redis. Auto-reset at market open clears the accumulators.
**When to use:** Every loss limit check; startup recovery; scheduled reset.
**Example:**
```python
# Redis state structure
# Key: "risk:circuit_breaker:paper" or "risk:circuit_breaker:live"
# Fields:
#   daily_realized_loss: float (accumulated loss today)
#   weekly_realized_loss: float (accumulated loss this week)
#   daily_halted: "true" | "false"
#   weekly_halted: "true" | "false"
#   halted_at: ISO timestamp or empty
#   last_reset_daily: ISO timestamp
#   last_reset_weekly: ISO timestamp

async def check_circuit_breaker(redis: Redis, mode: str) -> RiskDecision | None:
    """Check if circuit breaker is active. Returns rejection if halted."""
    key = f"risk:circuit_breaker:{mode}"
    state = await redis.hgetall(key)
    if state.get("daily_halted") == "true":
        return RiskDecision(
            approved=False,
            violated_rule=ViolatedRule.DAILY_LOSS_LIMIT,
            details=f"Daily loss limit breached at {state.get('halted_at', 'unknown')}",
        )
    if state.get("weekly_halted") == "true":
        return RiskDecision(
            approved=False,
            violated_rule=ViolatedRule.WEEKLY_LOSS_LIMIT,
            details=f"Weekly loss limit breached at {state.get('halted_at', 'unknown')}",
        )
    return None
```

### Pattern 3: Fail-Safe Default (Unreachable = Block)
**What:** The risk manager is invoked via a method call with a timeout wrapper. If the manager is unreachable (e.g., Redis down, internal error, timeout), the result is always rejection. The caller never proceeds without an explicit approval.
**When to use:** Every trade submission path.
**Example:**
```python
async def evaluate_with_failsafe(
    risk_manager: RiskManager,
    proposal: TradeProposal,
    timeout: float = 10.0,
) -> RiskDecision:
    """Evaluate a trade proposal with fail-safe timeout.

    If evaluation fails for ANY reason, the trade is rejected.
    """
    try:
        return await asyncio.wait_for(
            risk_manager.check_trade(proposal),
            timeout=timeout,
        )
    except Exception:
        return RiskDecision(
            approved=False,
            violated_rule=ViolatedRule.RISK_MANAGER_UNAVAILABLE,
            details="Risk manager evaluation failed or timed out",
        )
```

### Pattern 4: Dry-Run Mode
**What:** `check_trade(proposal, dry_run=True)` evaluates all rules but does not update any accumulators (loss tracking, position counts). Enables agents to pre-screen proposals.
**When to use:** Agent pre-screening before committing to a trade.

### Pattern 5: whatIfOrder Margin Check with Timeout
**What:** Wraps `ib.whatIfOrderAsync(contract, order)` with `asyncio.wait_for(timeout=5.0)`. Timeout falls through (does not reject). Result is stored in the RiskDecision for audit. Margin fields are strings that need float parsing.
**When to use:** Every trade, after rule-based checks pass.
**Example:**
```python
async def check_margin(
    ib: IB, contract: Contract, order: Order, timeout: float = 5.0
) -> MarginResult:
    """Check margin impact via IB whatIfOrder.

    Returns MarginResult with parsed fields. On timeout, returns
    a MarginResult with timed_out=True (non-blocking).
    """
    try:
        order_state = await asyncio.wait_for(
            ib.whatIfOrderAsync(contract, order),
            timeout=timeout,
        )
        # OrderState margin fields are strings, need parsing
        return MarginResult(
            init_margin_after=_parse_margin_str(order_state.initMarginAfter),
            maint_margin_after=_parse_margin_str(order_state.maintMarginAfter),
            equity_with_loan_after=_parse_margin_str(order_state.equityWithLoanAfter),
            commission=order_state.commission if order_state.commission != 1.7976931348623157e+308 else None,
            warning_text=order_state.warningText or None,
            timed_out=False,
        )
    except asyncio.TimeoutError:
        return MarginResult(timed_out=True)

def _parse_margin_str(value: str) -> float | None:
    """Parse IB margin string to float. Returns None for empty/invalid."""
    if not value or value == "":
        return None
    try:
        result = float(value)
        # IB uses UNSET_DOUBLE (max float) for unset values
        if result > 1e300:
            return None
        return result
    except (ValueError, TypeError):
        return None
```

### Anti-Patterns to Avoid
- **Mutable global state for limits:** Never store risk limits in module-level variables. Use the config system (YAML + Postgres overrides) and pass limits explicitly to evaluators.
- **Catching exceptions silently in evaluators:** Every evaluator must either return a clear pass/fail or propagate the exception to trigger the fail-safe.
- **Combining circuit breaker check with rule evaluation:** Circuit breaker check should be the FIRST evaluator, before any other rule. If halted, skip all other processing.
- **Relying solely on Redis for circuit breaker state:** Redis is volatile. Always persist halt state to Postgres on breach. On startup, always load from Postgres, not Redis.
- **Accumulating mark-to-market losses:** Per the decision, only realized losses (closed trades) count toward loss limits. Mark-to-market creates false positives on short options.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Config validation with numeric constraints | Custom validation loops | Pydantic `Field(gt=0, le=1.0)` and `@field_validator` | Pydantic already validates types, ranges, and provides clear error messages on startup |
| YAML config with env var interpolation | Custom `os.environ` parsing | `pyaml_env.parse_config()` (already used) | Already in codebase; handles ${VAR:default} syntax |
| Async Redis hash operations | Custom serialization layer | `redis.asyncio` HSET/HGETALL with `decode_responses=True` (already configured) | Already configured in project; handles all encoding |
| Pre-trade margin simulation | Custom margin calculation | `ib.whatIfOrderAsync(contract, order)` | IB's own margin engine is authoritative; no way to replicate externally |
| Greeks sign conventions for shorts | Custom sign-flipping logic | Multiply Greeks by position sign (+1 for long, -1 for short) and quantity | Standard options math; delta of -1 short put = +1 * (-delta) * quantity |
| Database migration management | Raw SQL scripts | Alembic migration (003_risk_engine_schema.py) | Already established pattern in project |
| Timezone-aware market open detection | Manual UTC offset calculation | `zoneinfo.ZoneInfo("America/New_York")` from stdlib | Python 3.12+ includes zoneinfo; handles DST correctly |

**Key insight:** This phase is almost entirely custom business logic (rules evaluation, circuit breaker semantics, naked options detection). The "don't hand-roll" items are about infrastructure (config, persistence, margin checks) -- use the established patterns. The rules themselves are inherently custom and should be straightforward functions.

## Common Pitfalls

### Pitfall 1: OrderState Margin Fields are Strings
**What goes wrong:** `OrderState.initMarginAfter` and similar fields are `str`, not `float`. Code that does numeric comparison without parsing breaks at runtime.
**Why it happens:** IB's API returns margin values as formatted strings (e.g., "12345.67"). The ib_async/ib_insync `OrderState` dataclass preserves this as `str`.
**How to avoid:** Always parse with `float()` and handle empty strings. Check for IB's `UNSET_DOUBLE` sentinel (1.7976931348623157e+308, which is `sys.float_info.max`).
**Warning signs:** Tests pass with mock data but fail against real IB Gateway.

### Pitfall 2: OrderState Commission Uses UNSET_DOUBLE
**What goes wrong:** `OrderState.commission` is a `float` but defaults to `UNSET_DOUBLE` (max float ~1.7e+308), not 0 or None. Comparing `commission > threshold` always triggers.
**Why it happens:** IB uses a sentinel value pattern instead of None/Optional.
**How to avoid:** Check `if order_state.commission < 1e300` before using the value.
**Warning signs:** Every trade appears to have astronomical commission cost.

### Pitfall 3: Redis State Lost on Restart Without Postgres Sync
**What goes wrong:** Circuit breaker halt state is only in Redis. Redis restarts (or flush) clears it. System resumes trading after a loss limit breach.
**Why it happens:** Developer puts state in Redis for speed but forgets persistence.
**How to avoid:** ALWAYS write halt state to Postgres first, then Redis. On startup, ALWAYS load from Postgres to Redis. Redis is cache, Postgres is truth.
**Warning signs:** After system restart following a halt, trading resumes without manual reset.

### Pitfall 4: Race Condition in Loss Accumulation
**What goes wrong:** Two concurrent trade closures both read the current loss total, add their loss, and write back. One write overwrites the other. Total loss is understated.
**Why it happens:** Non-atomic read-modify-write on Redis counter.
**How to avoid:** Use Redis HINCRBYFLOAT for atomic increment of loss accumulators. Never read-then-write.
**Warning signs:** Loss total is sometimes less than the sum of individual realized losses.

### Pitfall 5: Auto-Reset Clears Active Halt Prematurely
**What goes wrong:** Daily reset at 9:30am ET clears a halt that was triggered at 3:55pm the previous day. Halt should persist until the configured reset time, but reset logic runs before checking if the halt is still relevant.
**Why it happens:** Reset logic treats all halt states uniformly without checking breach timestamp.
**How to avoid:** Record `halted_at` timestamp with every breach. Daily reset only clears daily halt; weekly reset only clears weekly halt. Weekly halt persists through daily resets.
**Warning signs:** Weekly loss limit halt is cleared by the next day's daily reset.

### Pitfall 6: Greeks Sign Convention Errors
**What goes wrong:** Portfolio delta shows long exposure when the portfolio is actually short delta. Position sizing appears correct but exposure limits are wrong.
**Why it happens:** Forgetting that selling an option flips the sign of all Greeks. A sold call has negative delta; a sold put has positive delta (from the seller's perspective).
**How to avoid:** Standardize on the convention: `position_delta = contract_delta * position_sign * quantity * multiplier`. Where `position_sign = +1` for long, `-1` for short.
**Warning signs:** Portfolio Greeks don't match broker's risk summary.

### Pitfall 7: Naked Options Detection Ignores Existing Portfolio
**What goes wrong:** System rejects a "naked put sell" that is actually part of a spread (e.g., the trader already holds a lower-strike put). Or system approves a naked call when no underlying stock is held.
**Why it happens:** Detection only looks at the current proposal, not existing positions.
**How to avoid:** Naked options check must consider: (1) current open positions in the same underlying, (2) all legs of the current proposal as a unit. A short call is covered if the portfolio holds >= quantity * 100 shares of the underlying, or if there is a corresponding long call at a different strike.
**Warning signs:** Spreads are rejected; truly naked options are approved.

### Pitfall 8: whatIfOrder Blocking the Event Loop
**What goes wrong:** `whatIfOrder` (sync version) blocks the asyncio event loop, causing all market data updates and other async operations to stall.
**Why it happens:** Using the blocking `whatIfOrder()` instead of `whatIfOrderAsync()`.
**How to avoid:** Always use `whatIfOrderAsync()` wrapped with `asyncio.wait_for(timeout=5.0)`.
**Warning signs:** System becomes unresponsive for seconds during trade evaluation.

## Code Examples

Verified patterns from official sources and existing codebase:

### Risk Limits Configuration Model
```python
# Source: Existing codebase config.py pattern + Pydantic Field constraints
from pydantic import BaseModel, Field, field_validator

class PositionLimits(BaseModel):
    """Position sizing limits."""
    max_position_pct: float = Field(default=0.05, gt=0, le=1.0, description="Max % of portfolio per trade")
    max_contracts: int = Field(default=10, gt=0, description="Max contracts per trade")
    max_dollars: float = Field(default=5000.0, gt=0, description="Max dollar amount per trade")

class GreeksLimits(BaseModel):
    """Portfolio-level Greeks exposure caps."""
    max_delta: float = Field(default=500.0, gt=0, description="Max absolute portfolio delta")
    max_gamma: float = Field(default=100.0, gt=0, description="Max absolute portfolio gamma")
    max_theta: float = Field(default=-500.0, description="Max negative theta (daily decay)")
    max_vega: float = Field(default=1000.0, gt=0, description="Max absolute portfolio vega")

class LossLimits(BaseModel):
    """Daily and weekly realized loss limits."""
    daily_max_loss: float = Field(default=1000.0, gt=0, description="Max daily realized loss ($)")
    weekly_max_loss: float = Field(default=3000.0, gt=0, description="Max weekly realized loss ($)")

class StrategyRestrictions(BaseModel):
    """Strategy allowlist and restrictions."""
    allowed_strategies: list[str] = [
        "covered_call", "cash_secured_put", "vertical_spread",
        "iron_condor", "iron_butterfly", "calendar_spread",
    ]
    allow_naked_options: bool = False

class RiskLimitsConfig(BaseModel):
    """Complete risk limits with paper/live separation."""
    paper: RiskLimitsProfile = RiskLimitsProfile()
    live: RiskLimitsProfile = RiskLimitsProfile()

class RiskLimitsProfile(BaseModel):
    """Risk limits for a single trading mode."""
    position: PositionLimits = PositionLimits()
    greeks: GreeksLimits = GreeksLimits()
    loss: LossLimits = LossLimits()
    strategy: StrategyRestrictions = StrategyRestrictions()
    margin_check_timeout: float = Field(default=5.0, gt=0, le=30.0)
    emergency_halt: bool = False  # Runtime override via admin command

    @field_validator("position", "greeks", "loss", mode="before")
    @classmethod
    def validate_not_none(cls, v):
        """Ensure sub-configs are never None."""
        if v is None:
            raise ValueError("Risk limit section cannot be None")
        return v
```

### YAML Risk Limits Section
```yaml
# In config/default.yml (extends existing structure)
risk_limits:
  paper:
    position:
      max_position_pct: 0.10
      max_contracts: 20
      max_dollars: 10000.0
    greeks:
      max_delta: 1000.0
      max_gamma: 200.0
      max_theta: -1000.0
      max_vega: 2000.0
    loss:
      daily_max_loss: 2000.0
      weekly_max_loss: 5000.0
    strategy:
      allowed_strategies:
        - covered_call
        - cash_secured_put
        - vertical_spread
        - iron_condor
      allow_naked_options: false
  live:
    position:
      max_position_pct: 0.05
      max_contracts: 10
      max_dollars: 5000.0
    greeks:
      max_delta: 500.0
      max_gamma: 100.0
      max_theta: -500.0
      max_vega: 1000.0
    loss:
      daily_max_loss: 1000.0
      weekly_max_loss: 3000.0
    strategy:
      allowed_strategies:
        - covered_call
        - cash_secured_put
        - vertical_spread
      allow_naked_options: false
```

### Evaluator Function Pattern
```python
# Source: Custom, following existing codebase function patterns
def evaluate_position_size(
    proposal: TradeProposal,
    limits: PositionLimits,
) -> RiskDecision | None:
    """Check position sizing limits. Returns None if passed."""
    max_dollar_value = proposal.max_loss  # Worst-case dollar exposure

    # Check dollar limit
    if max_dollar_value > limits.max_dollars:
        return RiskDecision(
            approved=False,
            violated_rule=ViolatedRule.POSITION_SIZE_DOLLARS,
            details=f"Max loss ${max_dollar_value:,.2f} exceeds limit ${limits.max_dollars:,.2f}",
        )

    # Check contract limit
    total_contracts = sum(abs(leg.quantity) for leg in proposal.legs if leg.sec_type == "OPT")
    if total_contracts > limits.max_contracts:
        return RiskDecision(
            approved=False,
            violated_rule=ViolatedRule.POSITION_SIZE_CONTRACTS,
            details=f"{total_contracts} contracts exceeds limit {limits.max_contracts}",
        )

    # Check portfolio percentage
    if proposal.account_value > 0:
        pct = max_dollar_value / proposal.account_value
        if pct > limits.max_position_pct:
            return RiskDecision(
                approved=False,
                violated_rule=ViolatedRule.POSITION_SIZE_PERCENT,
                details=f"{pct:.1%} of portfolio exceeds limit {limits.max_position_pct:.1%}",
            )

    return None  # All checks passed
```

### Circuit Breaker Redis State Operations
```python
# Source: redis.asyncio patterns consistent with existing codebase
import redis.asyncio as aioredis
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 30

async def record_realized_loss(
    redis: aioredis.Redis, mode: str, loss_amount: float
) -> None:
    """Atomically accumulate a realized loss and check limits."""
    key = f"risk:circuit_breaker:{mode}"
    # HINCRBYFLOAT is atomic -- no race condition
    new_daily = await redis.hincrbyfloat(key, "daily_realized_loss", loss_amount)
    new_weekly = await redis.hincrbyfloat(key, "weekly_realized_loss", loss_amount)
    return float(new_daily), float(new_weekly)

async def activate_halt(
    redis: aioredis.Redis,
    mode: str,
    halt_type: str,  # "daily" or "weekly"
    session_factory,  # For Postgres persistence
) -> None:
    """Activate circuit breaker halt in both Redis and Postgres."""
    key = f"risk:circuit_breaker:{mode}"
    now = datetime.now(timezone.utc).isoformat()

    # Redis first (for immediate effect)
    await redis.hset(key, f"{halt_type}_halted", "true")
    await redis.hset(key, "halted_at", now)

    # Postgres second (for persistence across restarts)
    async with get_session(session_factory) as session:
        state = CircuitBreakerState(
            mode=mode,
            halt_type=halt_type,
            halted=True,
            halted_at=datetime.now(timezone.utc),
        )
        await session.merge(state)

async def check_and_reset_at_market_open(
    redis: aioredis.Redis, mode: str
) -> None:
    """Auto-reset accumulators at market open (9:30am ET)."""
    now_et = datetime.now(ET)
    key = f"risk:circuit_breaker:{mode}"

    last_daily_reset = await redis.hget(key, "last_reset_daily")
    # Reset daily if it's past 9:30am and we haven't reset today
    if now_et.hour >= MARKET_OPEN_HOUR and now_et.minute >= MARKET_OPEN_MINUTE:
        if not last_daily_reset or last_daily_reset[:10] != now_et.date().isoformat():
            await redis.hset(key, "daily_realized_loss", "0.0")
            await redis.hset(key, "daily_halted", "false")
            await redis.hset(key, "last_reset_daily", now_et.isoformat())

    # Reset weekly on Monday
    if now_et.weekday() == 0:  # Monday
        last_weekly_reset = await redis.hget(key, "last_reset_weekly")
        if not last_weekly_reset or last_weekly_reset[:10] != now_et.date().isoformat():
            await redis.hset(key, "weekly_realized_loss", "0.0")
            await redis.hset(key, "weekly_halted", "false")
            await redis.hset(key, "last_reset_weekly", now_et.isoformat())
```

### Database Schema for Risk Decisions
```python
# Source: Following existing db/models.py ORM patterns
class RiskDecisionRecord(Base):
    """Audit log of all risk evaluations."""
    __tablename__ = "risk_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    proposal_id: Mapped[str] = mapped_column(String(36), nullable=False)
    approved: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    violated_rule: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    details: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    strategy_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    max_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    dry_run: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    mode: Mapped[str] = mapped_column(String(10), nullable=False)

    # whatIfOrder audit fields
    margin_init_after: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    margin_maint_after: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    equity_with_loan_after: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    estimated_commission: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    margin_warning: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    margin_check_timed_out: Mapped[bool] = mapped_column(sa.Boolean, default=False)

    __table_args__ = (
        Index("ix_risk_decisions_ts", "timestamp"),
        Index("ix_risk_decisions_proposal", "proposal_id"),
    )

class CircuitBreakerState(Base):
    """Persistent circuit breaker state for crash recovery."""
    __tablename__ = "circuit_breaker_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    halt_type: Mapped[str] = mapped_column(String(10), nullable=False)  # "daily" or "weekly"
    halted: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    halted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    daily_realized_loss: Mapped[float] = mapped_column(Float, default=0.0)
    weekly_realized_loss: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        sa.UniqueConstraint("mode", "halt_type", name="uq_cb_mode_halt_type"),
    )
```

### Naked Options Detection Logic
```python
# Source: Standard options theory applied to position validation
def is_naked_option(
    proposal: TradeProposal,
    existing_positions: list[Position],
) -> bool:
    """Detect if a proposal contains naked (uncovered) short options.

    A short call is covered if:
    - Portfolio holds >= quantity * 100 shares of the underlying, OR
    - Proposal or portfolio has a long call on same underlying (spread)

    A short put is covered if:
    - Proposal or portfolio has a long put on same underlying (spread), OR
    - Cash/margin is sufficient (handled by margin check separately)
    - For "cash-secured put": not considered naked

    Returns True if any leg is a naked short option.
    """
    short_options = [
        leg for leg in proposal.legs
        if leg.sec_type == "OPT" and leg.action == "SELL"
    ]

    if not short_options:
        return False

    for short_leg in short_options:
        underlying = short_leg.symbol

        # Check if there's a covering long option in the same proposal
        has_covering_long = any(
            leg.sec_type == "OPT" and leg.action == "BUY"
            and leg.symbol == underlying
            for leg in proposal.legs
        )
        if has_covering_long:
            continue

        # Check if portfolio has covering stock position (for calls)
        if _is_call(short_leg):
            shares_held = sum(
                p.quantity for p in existing_positions
                if p.symbol == underlying and p.sec_type == "STK" and p.quantity > 0
            )
            needed_shares = abs(short_leg.quantity) * 100
            if shares_held >= needed_shares:
                continue

        # Check if portfolio has a covering long option
        has_portfolio_cover = any(
            p.symbol == underlying and p.sec_type == "OPT"
            and p.quantity > 0  # Long position
            for p in existing_positions
        )
        if has_portfolio_cover:
            continue

        # This short option is naked
        return True

    return False
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| ib_insync library | ib_async (fork, maintained) | 2024 (after author's passing) | Same API, new package name, actively maintained |
| Sync Redis with circuit breaker | Async redis.asyncio with HINCRBYFLOAT | redis-py 4.2+ (2022) | No event loop blocking; atomic operations |
| Manual timezone handling | `zoneinfo.ZoneInfo` (stdlib) | Python 3.9+ (2020) | No pytz dependency; correct DST handling |
| Pydantic v1 Field constraints | Pydantic v2 `Field(gt=0)` with Annotated | Pydantic 2.0 (2023) | Better validation errors; faster |
| ib_insync OrderState float fields | ib_async OrderState still uses str for margins | Unchanged | Must parse strings to floats; watch for UNSET_DOUBLE |

**Deprecated/outdated:**
- `ib_insync`: Replaced by `ib_async`. API is identical but package name changed. This project already uses `ib_async`.
- `pytz`: Replaced by `zoneinfo` in Python 3.9+. Use `zoneinfo.ZoneInfo("America/New_York")` for ET timezone.
- `aioredis`: Merged into `redis-py` as `redis.asyncio`. This project already uses `redis[hiredis]`.

## Open Questions

Things that couldn't be fully resolved:

1. **whatIfOrder for Multi-Leg Orders**
   - What we know: `whatIfOrderAsync` takes a single `(contract, order)` pair. IB combo orders exist but their whatIfOrder support is inconsistent.
   - What's unclear: Whether to call whatIfOrder once per leg or construct a combo order. Per-leg calls may overstate margin impact.
   - Recommendation: Start with per-leg calls summed. If margin checks seem too conservative, investigate IB combo orders in a future iteration. The margin check is non-blocking on timeout anyway, so false conservatism is acceptable for safety.

2. **Portfolio Greeks Source at Check Time**
   - What we know: Phase 2 stores Greeks snapshots in the option_greeks table. The risk engine needs current portfolio-level Greeks to check exposure limits.
   - What's unclear: Whether to compute portfolio Greeks from cached Phase 2 data or query IB positions directly.
   - Recommendation: Use Phase 2's Greeks data (from Redis cache or DB) for the portfolio snapshot. The risk engine should not make additional IB API calls beyond whatIfOrder. Accept that Greeks may be slightly stale (within the staleness threshold from Phase 2 config).

3. **Postgres Override Mechanism for Runtime Limits**
   - What we know: YAML provides defaults; Postgres DB overrides take precedence. Emergency tighten mode writes to Postgres.
   - What's unclear: Exact schema for the runtime override table. Whether it stores full limit profiles or individual field overrides.
   - Recommendation: Use a simple key-value approach: `risk_limit_overrides` table with `(mode, key_path, value, updated_at)`. On startup, merge overrides into the loaded YAML config. Emergency halt is a single boolean override.

4. **Loss Recording Trigger**
   - What we know: Realized losses are tracked when trades close. The risk engine accumulates losses against limits.
   - What's unclear: What component calls `record_realized_loss()` -- the order tracker, a fill handler, or the risk engine itself.
   - Recommendation: The risk engine exposes `record_realized_loss(amount)` as a public method. The calling component (likely the order tracker or fill handler from Phase 4) invokes it when a position is closed at a loss. For Phase 3, the interface is defined and tested; the integration happens in Phase 4.

## Sources

### Primary (HIGH confidence)
- [ib_async API docs](https://ib-api-reloaded.github.io/ib_async/api.html) - whatIfOrder method signature and behavior
- [ib_async source code](https://github.com/ib-api-reloaded/ib_async/blob/main/ib_async/order.py) - OrderState dataclass fields (17 fields including margin strings and commission float)
- [IB TWS API margin docs](https://interactivebrokers.github.io/tws-api/margin.html) - whatIfOrder concept and OrderState fields
- Existing codebase (src/trading/) - All patterns: config, Redis, DB, models, state machine, structlog
- [Pydantic Fields docs](https://docs.pydantic.dev/latest/concepts/fields/) - Field(gt=0) constraints, PositiveInt, validation

### Secondary (MEDIUM confidence)
- [ib_insync ordering notebook](https://github.com/erdewit/ib_insync/blob/master/notebooks/ordering.ipynb) - whatIfOrder usage examples and output format
- [ib_insync OrderState issue #380](https://github.com/erdewit/ib_insync/issues/380) - Known issues with whatIfOrder returning incorrect data
- [redis-py asyncio examples](https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html) - Async Redis hash operations
- [pybreaker docs](https://github.com/danielfm/pybreaker) - Circuit breaker pattern with Redis storage (used as reference, not dependency)

### Tertiary (LOW confidence)
- WebSearch results on naked options detection algorithms - General financial theory, no specific library
- WebSearch results on trading risk engine architecture - General patterns, validated against existing codebase

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries already in project; no new dependencies
- Architecture: HIGH - Evaluator chain pattern is well-established; codebase patterns are clear from Phase 1/2
- Pitfalls: HIGH - whatIfOrder field types verified from ib_async source code; Redis atomicity is documented
- Code examples: MEDIUM - Examples follow existing patterns but are untested drafts
- Open questions: MEDIUM - Multi-leg whatIfOrder behavior needs runtime validation

**Research date:** 2026-04-03
**Valid until:** 2026-05-03 (30 days - stable domain, no fast-moving dependencies)
