# Feature Landscape: AI-Powered Options Trading System

**Domain:** Multi-agent AI options trading via Interactive Brokers
**Researched:** 2026-03-25
**Overall confidence:** MEDIUM-HIGH (features well-established in industry; AI-agent layer is emerging)

---

## Table Stakes

Features users expect. Missing any of these and the system feels incomplete, unsafe, or unusable. Organized by functional area.

### Brokerage Connectivity & Order Execution

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| IB TWS/Gateway API connection with auto-reconnect | Cannot trade without it; disconnections are common | Med | IB Gateway preferred over TWS for headless operation; lighter resource footprint. Must handle socket drops, daily server resets (IB restarts at ~23:45 ET), and version handshake. Confidence: HIGH (IB docs) |
| Order placement (market, limit, stop) | Basic execution capability | Low | IB TWS API supports all standard order types. Confidence: HIGH |
| Multi-leg combo/spread orders | Options strategies are multi-leg by nature; single-leg-only is a non-starter | Med | IB supports BAG security type for combos, up to 6 legs guaranteed. Supports REL+MKT, LMT+MKT for smart fill. Confidence: HIGH (IB docs) |
| Order state tracking & management | Must know if orders are pending, filled, partially filled, cancelled, or errored | Med | IB provides orderStatus callbacks but they can be unreliable (duplicate callbacks, out-of-order). Need local state machine. Confidence: HIGH |
| Paper trading toggle | Industry standard for strategy validation; IB natively supports paper accounts | Low | Same API, different port (7497 paper vs 7496 live). Same codebase, config-driven switch. Confidence: HIGH (IB docs) |
| Option chain retrieval | Must discover available strikes, expirations, and contract specs | Low-Med | reqSecDefOptParams (no throttle) for chain metadata; reqContractDetails for specifics. Different handling for equity vs ETF vs futures options. Confidence: HIGH |

### Risk Management

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Position sizing limits | Prevents oversized bets; every serious trading system has this | Low | Configurable per-trade max dollar amount, max contracts, max % of portfolio. Confidence: HIGH (universal pattern) |
| Greeks exposure limits (portfolio-level delta, gamma, theta, vega) | Options traders live and die by Greeks; unmanaged Greeks exposure is the #1 account-blowing risk | Med-High | Must aggregate Greeks across all positions in real-time. IB provides per-contract Greeks via market data but portfolio aggregation is your responsibility. Confidence: HIGH |
| Daily/weekly loss limits (drawdown circuit breakers) | Industry standard; prevents catastrophic loss spirals | Med | Hard stop: when daily P&L hits threshold, cease all new trades and optionally flatten positions. Must survive agent restarts (persist state). Confidence: HIGH |
| Strategy restrictions (e.g., no naked options) | Prevents accidentally taking on unlimited-risk positions | Med | Rule engine that validates proposed trades against allowed strategy types before execution. Naked short calls = unlimited risk. Confidence: HIGH |
| Fail-safe: if risk manager unreachable, block all trades | Non-negotiable safety; stated in project constraints | Med | Risk manager must be a hard gate, not advisory. If the risk management agent is down or unresponsive, the executor must refuse all orders. Confidence: HIGH (project requirement) |
| Margin check before order submission | IB will reject orders exceeding margin but you should pre-validate to avoid wasted API calls and potential partial fills on combos | Med | IB provides account margin data; pre-calculate expected margin impact. Confidence: MEDIUM |

### Market Data & Analytics

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Real-time market data (quotes, bid/ask, volume) | Cannot make trading decisions without it | Med | IB provides streaming market data via reqMktData. Subject to rate limits (~100 simultaneous subscriptions on non-professional accounts). Confidence: HIGH |
| Real-time Greeks per contract | Options-specific; required for risk management and strategy selection | Med | IB streams delta, gamma, theta, vega, implied volatility via option model data. Confidence: HIGH (IB docs) |
| Implied volatility per contract and underlying | Core to options pricing decisions; every options platform shows this | Med | Available from IB; also needed to detect IV rank/percentile for strategy selection. Confidence: HIGH |
| Options open interest and volume | Liquidity assessment; avoids illiquid strikes | Low | Available from IB market data. Critical for strike selection. Confidence: HIGH |

### Dashboard & Monitoring

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Positions display with real-time P&L | Basic portfolio visibility; every trading platform has this | Med | Show per-position and portfolio-level unrealized/realized P&L. Group by underlying, strategy type. Confidence: HIGH |
| Portfolio-level Greeks display | Aggregated delta, gamma, theta, vega across all positions | Med | Critical for at-a-glance risk assessment. Confidence: HIGH |
| Trade history log | Audit trail of all trades executed | Low-Med | Timestamp, underlying, strategy, legs, fill prices, reasoning. Confidence: HIGH |
| Agent decision/reasoning display | Without this, the system is a black box; trust requires transparency | Med-High | Each agent's reasoning chain must be logged and viewable. This is what makes an LLM-based system auditable. Confidence: HIGH (TradingAgents framework validates this pattern) |
| System health indicators | Must know if agents are running, API connected, data flowing | Low-Med | Heartbeats, connection status, last data timestamp, error counts. Confidence: HIGH |

### Alerts & Notifications

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Trade execution alerts (Slack/SMS/email) | Must know when trades happen, especially auto-executed ones | Low-Med | Slack webhooks are simplest. SMS via Twilio/SNS. Include key details: underlying, strategy, price, Greeks impact. Confidence: HIGH |
| Risk event alerts (limit breach, circuit breaker trigger) | Critical safety visibility; must notify immediately | Low-Med | Higher urgency than trade alerts. Should be real-time push, not polled. Confidence: HIGH |
| System error/downtime alerts | Must know when something breaks | Low | Connection lost, agent crash, data feed stale. Confidence: HIGH |

### Hybrid Autonomy

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Configurable auto-execute threshold | Core project concept; small trades auto-execute, large ones need approval | Med | Threshold by dollar amount, Greeks impact, strategy complexity. Configurable per user. Confidence: HIGH (project requirement) |
| Approval workflow for large trades | Human-in-the-loop for significant risk decisions | Med | Present trade proposal with full context (reasoning, Greeks impact, P&L scenarios). Allow approve/reject/modify via dashboard or Slack. Timeout behavior must be defined (default reject). Confidence: MEDIUM |
| Approval timeout with safe default | If human doesn't respond, trade opportunity passes; default must be safe | Low | Default: reject/expire. Do not default to execute. Confidence: HIGH (safety principle) |

---

## Differentiators

Features that set this system apart. Not expected by default, but highly valued when present. These are where the "AI-powered" and "multi-agent" aspects create competitive advantage.

### AI Agent Intelligence

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Multi-agent pipeline (scanner -> strategist -> risk manager -> executor) | Separation of concerns mirrors real trading firms; each agent specializes. Easier to debug, improve, and audit than monolithic bot | High | TradingAgents framework validates this pattern. Key: agents must have well-defined interfaces and structured communication. Confidence: MEDIUM (novel for personal systems) |
| LLM + quant hybrid reasoning | LLMs excel at research synthesis, news interpretation, and reasoning; quant models excel at signals, pricing, Greeks. Combining both is state of the art | High | LLMs handle: market research, earnings analysis, news sentiment, trade rationale. Quant handles: signals, pricing, Greeks calc, volatility modeling. Do NOT use LLMs for precise numerical calculations. Confidence: MEDIUM |
| Agent reasoning chain logging with natural language explanations | Every decision is auditable in plain English; massive trust advantage over black-box algos | Med | LLM agents naturally produce reasoning; the key is capturing and structuring it. P1GPT and TradingAgents both emphasize this. Confidence: MEDIUM |
| Market regime detection (bull/bear/sideways/volatile) | Adapts strategy selection to current market conditions instead of static rules | High | Hidden Markov Models or clustering (KMeans) on returns + volatility. Switch strategy mix based on detected regime. Academic research shows strong results (Sharpe 6.83 on gold futures in one study). Confidence: MEDIUM (implementation complexity) |
| Earnings event awareness | Options strategies differ dramatically pre vs post earnings; system must know earnings calendar and adjust | Med | Pre-earnings: exploit IV expansion. Post-earnings: exploit IV crush. Must integrate earnings calendar data. Confidence: HIGH (well-understood domain) |

### Advanced Options Intelligence

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| IV rank/percentile analysis | Determines whether current IV is high or low relative to history; drives strategy selection (sell high IV, buy low IV) | Med | Compare current IV to 52-week range. IV rank = (current - low) / (high - low). IV percentile = % of days below current. Confidence: HIGH |
| Volatility surface and skew analysis | Identifies mispriced options by analyzing IV across strikes and expirations; professional-grade edge | High | 3D surface: strike x expiration x IV. Detect skew anomalies, term structure (contango vs backwardation). ORATS is gold standard data provider. Confidence: MEDIUM (implementation complexity, data cost) |
| Unusual options activity detection | Identifies institutional flow that may signal upcoming moves; adds an information edge | High | Volume > 5x average daily, large block trades, sweep orders. Requires real-time options flow data beyond what IB provides. May need external data source (e.g., CBOE, OPRA feed). Confidence: LOW (external data dependency) |
| Automated position rolling | Proactively manages expiring positions by rolling to new expiration; reduces manual intervention | Med-High | Detect approaching expiration (e.g., < 5 DTE), evaluate whether to close or roll. Option Alpha's Exit Options feature does this. IB API supports closing old + opening new as atomic combo. Confidence: MEDIUM |
| Multi-asset options awareness (equity vs ETF vs futures options) | Different contract specs, multipliers, margin rules, trading hours per asset class | Med-High | Futures options: different multipliers (e.g., /ES options = $50/point), different expiration conventions, cash vs physical settlement. Must handle all three asset classes per project spec. Confidence: HIGH (project requirement, well-documented by IB) |

### Portfolio Intelligence

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Portfolio-level P&L scenario analysis (what-if) | Shows how portfolio responds to price moves, time decay, and IV changes | High | Calculate P&L under hypothetical conditions: underlying +/-X%, IV +/-Y%, T+N days. Present as payoff diagram or matrix. Confidence: MEDIUM |
| Correlation awareness across positions | Prevents overconcentration in correlated underlyings; real diversification | Med-High | Track sector/industry exposure. Two AAPL and MSFT positions are correlated; raw position count misleads. Confidence: MEDIUM |
| Dynamic hedge suggestions | When portfolio Greeks drift, suggest corrective trades | High | "Portfolio delta is +150; consider selling 3 SPY 520 calls to neutralize." LLM agent can synthesize this recommendation. Confidence: LOW (cutting edge) |

### User Experience

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Interactive approval via Slack (not just notifications) | Approve/reject trades without opening dashboard; faster response for time-sensitive opportunities | Med | Slack interactive messages with approve/reject buttons. Include context: strategy, Greeks, risk impact. Confidence: MEDIUM |
| Strategy performance attribution | Understand which strategies and agents are performing well vs poorly over time | Med-High | Track P&L by strategy type, by agent, by underlying, by market regime. Enables evidence-based tuning. Confidence: MEDIUM |
| Configurable strategy allowlist | Restrict system to only strategies the user understands and approves | Low | E.g., only allow covered calls, cash-secured puts, and vertical spreads. No butterflies, no calendars unless explicitly enabled. Confidence: HIGH |

---

## Anti-Features

Features to explicitly NOT build. Common mistakes in this domain that waste effort or create danger.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **HFT / sub-second latency optimization** | Options trading is not HFT; bid-ask spreads are wide, fills take seconds. Over-engineering latency wastes massive effort and adds fragile complexity | Target seconds-level execution latency. Focus on decision quality, not speed. IB API has 50 msg/sec limit anyway |
| **Backtesting engine in v1** | Explicitly out of scope per PROJECT.md. Backtesting is a massive engineering effort (data management, realistic fill simulation, survivorship bias handling) that delays the core trading system | Paper trading IS your v1 validation mechanism. Defer backtesting to v2. Use paper trading for 30-90 days as the industry recommends |
| **Custom options pricing models** | Black-Scholes and its variants are well-solved. Building a proprietary pricing model is PhD-level quant work with minimal marginal value for a trading system | Use IB-provided Greeks and IV. Supplement with open-source Black-Scholes libraries (e.g., `py_vollib`, `blackscholes` Python package) for what-if calculations |
| **Mobile native app** | Explicitly out of scope. Mobile-first trading UX is an enormous engineering surface area (responsive charts, order entry, real-time updates) | Web dashboard works on mobile browsers. Slack/SMS alerts provide mobile notification. The approval workflow via Slack gives mobile interaction |
| **Social/copy trading** | Explicitly out of scope. Single-user system. Social features add authentication, multi-tenancy, compliance, and community management complexity | Keep single-user. Add multi-user only if there's a clear future need |
| **LLM-based precise numerical calculations** | LLMs are unreliable for math. They hallucinate prices, miscalculate Greeks, and cannot reliably do options pricing arithmetic | Use LLMs for research, synthesis, reasoning, and natural language. Use quant code (Python, numpy) for all pricing, Greeks, signals, and numerical analysis. This is the hybrid approach |
| **Overly complex strategy generation** | Research shows complexity does not correlate with profitability; over-fitted strategies fail in live markets. Building tools that encourage 8-leg butterflies on illiquid underlyings is dangerous | Start with simple, well-understood strategies: covered calls, cash-secured puts, vertical spreads, iron condors. Add complexity only after simpler strategies prove profitable in paper trading |
| **Fully autonomous operation without circuit breakers** | Even institutional algo desks have kill switches and human oversight. A runaway bot can drain an account in minutes | Always have: max daily loss limit, max position count, max single-trade size, and a manual kill switch. Default to "stop all trading" on any anomaly |
| **Real-time alternative data (sentiment, news, social) as blocking dependency** | Alternative data APIs are expensive, unreliable, and add latency. Making them a hard requirement blocks the core system | Build the core system first. Add sentiment/news analysis as an enhancement layer. LLM agents can process news when available but must function without it |
| **Desktop GUI application** | Building a native desktop app is massive overhead vs a web application; no advantage for a personal trading dashboard | Web dashboard (React/Next.js or similar). Accessible from any device, easier to deploy and update |

---

## Feature Dependencies

Critical ordering constraints -- features that must exist before others can function.

```
IB API Connection & Authentication
  |
  +---> Market Data Streaming
  |       |
  |       +---> Real-time Greeks
  |       |       |
  |       |       +---> Portfolio Greeks Aggregation
  |       |       |       |
  |       |       |       +---> Greeks Exposure Limits
  |       |       |       +---> Portfolio-Level P&L Scenarios
  |       |       |
  |       |       +---> Risk Manager Agent
  |       |
  |       +---> IV Data
  |       |       |
  |       |       +---> IV Rank/Percentile
  |       |       +---> Strategy Selection Logic
  |       |
  |       +---> Scanner Agent (opportunity detection)
  |
  +---> Option Chain Retrieval
  |       |
  |       +---> Strike/Expiration Selection
  |       +---> Strategy Construction (Strategist Agent)
  |
  +---> Order Placement
  |       |
  |       +---> Order State Tracking
  |       +---> Multi-leg Combo Orders
  |       +---> Executor Agent
  |
  +---> Account Data (positions, P&L, margin)
          |
          +---> Position Sizing Limits
          +---> Daily Loss Tracking
          +---> Dashboard Positions View

Agent Pipeline Dependencies:
  Scanner Agent (requires: market data, option chains)
    |
    +---> Strategist Agent (requires: scanner output, IV data, option chains)
            |
            +---> Risk Manager Agent (requires: strategy proposal, portfolio Greeks, position limits)
                    |
                    +---> Executor Agent (requires: approved trade, IB order API)
                            |
                            +---> Alert System (requires: execution result)

Hybrid Autonomy Dependencies:
  Risk Manager Agent
    |
    +---> Threshold Evaluation
            |
            +-- Below threshold --> Auto-execute via Executor
            +-- Above threshold --> Approval Workflow
                                      |
                                      +---> Dashboard Approval UI
                                      +---> Slack Interactive Approval
```

---

## MVP Recommendation

For MVP (paper trading capable), prioritize in this order:

### Phase 1: Foundation (must work before anything else)
1. **IB API connection with auto-reconnect** -- everything depends on this
2. **Market data streaming (quotes, Greeks, IV)** -- agents need data to reason
3. **Option chain retrieval** -- must discover tradeable contracts
4. **Order placement and tracking (including combos)** -- must be able to execute
5. **Paper trading mode** -- validation without risk

### Phase 2: Risk & Safety (must work before any autonomous trading)
6. **Position sizing limits** -- prevent oversized trades
7. **Greeks exposure limits (portfolio-level)** -- prevent Greeks blowups
8. **Daily loss limits (circuit breakers)** -- prevent catastrophic loss
9. **Strategy restrictions** -- prevent unlimited-risk positions
10. **Risk manager fail-safe (block trades if risk mgr down)** -- non-negotiable safety

### Phase 3: Agent Pipeline (the core intelligence)
11. **Scanner agent** -- find opportunities
12. **Strategist agent** -- construct trades
13. **Risk manager agent** -- validate trades against all risk rules
14. **Executor agent** -- place validated trades
15. **Agent reasoning logging** -- capture decision chains

### Phase 4: Monitoring & Autonomy
16. **Web dashboard (positions, P&L, Greeks, trade history, agent reasoning)**
17. **Hybrid autonomy (auto-execute below threshold, approve above)**
18. **Alerts (Slack/SMS for trades, risk events, errors)**

### Defer to Post-MVP:
- **Backtesting engine**: Out of scope for v1; paper trading validates strategies
- **Volatility surface analysis**: Advanced; useful but not blocking
- **Unusual options activity detection**: Requires external data sources
- **Market regime detection**: Valuable but complex ML; can enhance scanner later
- **Portfolio P&L scenario analysis**: Useful dashboard feature, not blocking
- **Strategy performance attribution**: Need trade history first; add after running for weeks
- **Automated position rolling**: Requires stable position management first
- **Correlation awareness**: Enhancement after basic risk works
- **Dynamic hedge suggestions**: Cutting-edge; defer until portfolio management is proven

---

## Sources

### HIGH Confidence (official documentation)
- [IB TWS API Options Documentation](https://interactivebrokers.github.io/tws-api/options.html)
- [IB TWS API Spread Contracts](https://interactivebrokers.github.io/tws-api/spread_contracts.html)
- [IB TWS API Basic Orders](https://interactivebrokers.github.io/tws-api/basic_orders.html)
- [IB API Solutions Overview](https://www.interactivebrokers.com/en/trading/ib-api.php)
- [TWS API v9.72+ Introduction](https://interactivebrokers.github.io/tws-api/introduction.html)
- [IB TWS Python Complex Orders Lesson](https://www.interactivebrokers.com/campus/trading-lessons/python-complex-orders/)

### MEDIUM Confidence (multiple credible sources agree)
- [TradingAgents: Multi-Agent LLM Financial Trading Framework](https://tradingagents-ai.github.io/) -- validates multi-agent architecture pattern
- [TradingAgents (arxiv)](https://arxiv.org/abs/2412.20138) -- academic backing for agent pipeline
- [AI Options Trading Bot Development Guide](https://www.biz4group.com/blog/ai-options-trading-bot-development)
- [Option Alpha Automated Position Management](https://optionalpha.com/tools/exit-options)
- [ORATS Volatility Surface](https://orats.com/university/volatility-surface)
- [AI Trading Bot Risk Management Guide 2025](https://3commas.io/blog/ai-trading-bot-risk-management-guide-2025)
- [Options Trading Mistakes (IB Campus)](https://www.interactivebrokers.com/campus/traders-insight/securities/options/options-trading-mistakes-that-can-blow-up-your-account-and-how-to-avoid-them/)
- [Best AI-Powered Tools for Smarter Options Trading 2026](https://www.optionstrading.org/blog/top-ai-powered-tools-for-options-trading/)

### LOW Confidence (single source, unverified -- flagged for validation)
- Market regime detection performance claims (single academic study on gold futures)
- Unusual options activity detection via ML (emerging area, limited production evidence)
- Dynamic hedge suggestion generation by LLM agents (theoretical, no production examples found)
