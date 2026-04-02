# Phase 2: Market Data & Analytics - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Stream real-time quotes, Greeks, and implied volatility from IB into the system, compute IV rank/percentile analytics, and flag tickers approaching earnings events. This phase delivers the data infrastructure that the risk engine (Phase 3) and agent pipeline (Phase 5) depend on. No trading logic, no UI — pure data plumbing and analytics.

</domain>

<decisions>
## Implementation Decisions

### Data Distribution Model
- Claude's Discretion: choose the right distribution architecture (Redis pub/sub, TimescaleDB writes, or both) based on what downstream agent access patterns will actually need
- Claude's Discretion: decide on data retention policy for raw tick data
- Claude's Discretion: decide whether to maintain a latest-value cache in Redis for point-queries
- Claude's Discretion: choose staleness detection approach (timestamp-based vs heartbeat channel)

### Subscription Lifecycle
- Claude's Discretion: decide whether to use a static config watchlist, fully dynamic agent-driven subscriptions, or a hybrid seed + dynamic approach
- Claude's Discretion: choose the IB subscription limit strategy (LRU eviction, priority-based pinning for open positions, or hard cap)
- Claude's Discretion: decide whether to subscribe to underlyings only, individual option contracts, or both — based on what IB's API provides per subscription type
- Claude's Discretion: decide on off-hours subscription behavior (keep active vs unsubscribe at close) based on cost/complexity tradeoff

### Historical IV Data Source
- Claude's Discretion: choose the IV history sourcing strategy — IB historical data bootstrap, local accumulation, or a hybrid approach
- Claude's Discretion: decide cold-start behavior when no local IV history exists yet
- Claude's Discretion: choose IV rank/percentile computation strategy (on-demand, daily cache, or cache + intraday refresh)
- Claude's Discretion: choose IV history storage granularity (daily close vs intraday snapshots)

### Earnings Calendar Source
- Claude's Discretion: choose earnings date source (IB fundamentals API vs external provider such as Polygon.io) based on reliability and dependency tradeoff
- Claude's Discretion: decide the earnings lookout window (how many days ahead triggers the flag)
- Claude's Discretion: decide the earnings flag structure exposed to downstream agents — lean toward richer metadata (date, days_until, before/after_close) since agents will need that for strategy-specific logic
- Claude's Discretion: decide earnings calendar refresh cadence (daily pre-market vs periodic polling)

### Claude's Discretion
User delegated all implementation decisions in this phase to Claude. The phase is pure data infrastructure — the user trusts Claude to pick appropriate patterns. Where there are real tradeoffs (e.g., IB data quality vs external API reliability for earnings), the researcher should investigate and the planner should make a reasoned choice and document it.

</decisions>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches. The user has explicitly delegated all architectural and implementation choices to Claude for this infrastructure-heavy phase.

Key constraints to keep in mind (from Phase 1 decisions):
- Redis client uses `decode_responses=True` (string returns)
- TimescaleDB hypertables created via raw SQL migrations
- Cache errors are non-fatal — log warning, continue without cache
- OptionChain fields handled as lists for ib_async version compatibility

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 02-market-data-analytics*
*Context gathered: 2026-04-02*
