# Domain Pitfalls: AI-Powered Options Trading System

**Domain:** Multi-agent AI options trading with Interactive Brokers
**Researched:** 2026-03-25
**Overall Confidence:** MEDIUM-HIGH (cross-verified across academic research, IB official docs, and multiple practitioner sources)

---

## Critical Pitfalls

Mistakes that cause catastrophic financial loss, system rewrites, or regulatory action. Any one of these can kill the project or the account.

---

### Pitfall 1: No Kill Switch / Runaway Order Protection

**What goes wrong:** An agent enters a feedback loop, misinterprets a signal, or encounters a bug that causes it to submit orders continuously. Without a hard kill switch, the system floods the market with erroneous orders. Knight Capital lost $440 million in 45 minutes from exactly this failure -- a dormant algorithm activated without correct configuration, and no circuit breaker existed to stop it.

**Why it happens:** Teams focus on "making it work" before "making it safe." Kill switches feel like a nice-to-have during development. The assumption is "I'll just manually stop it" -- but automated systems can burn through capital in seconds, far faster than a human can react.

**Consequences:**
- Account liquidation within minutes
- IB auto-liquidation triggers at maintenance margin breach, potentially at worst possible prices
- Possible regulatory scrutiny (IB reports anomalous trading activity)
- FINRA fines -- IB was fined $650K in August 2025 for inadequate automated trading controls

**Prevention:**
- Build the kill switch BEFORE the first order is ever placed. This is Phase 1, not Phase N
- Implement hard limits at multiple layers: per-second order rate cap, per-minute dollar volume cap, per-day maximum loss, maximum position count
- Use IB's native order rate limit (50 msg/sec) as a backstop, but enforce your own tighter limit (e.g., 5 orders/sec)
- Every order must pass through a synchronous risk gate before submission -- never allow agents to bypass this
- Implement a "dead man's switch": if the risk manager agent stops responding, all new orders halt and existing positions get protective stop orders

**Detection:**
- Order submission rate exceeding 2x normal baseline
- P&L drawdown exceeding daily limit
- Position concentration exceeding threshold in any single underlying
- Agent response times degrading (suggests system instability)

**Phase:** Must be in Phase 1 (Foundation). Non-negotiable.

**Confidence:** HIGH -- Knight Capital case is exhaustively documented; IB's 50 msg/sec limit is from official API docs; FINRA fine from multiple news sources.

---

### Pitfall 2: LLM Hallucination in Financial Decision-Making

**What goes wrong:** The LLM component of the system fabricates analysis, invents nonexistent market conditions, misinterprets data, or confidently recommends trades based on hallucinated reasoning. The TradeTrap research paper (arXiv:2512.02261) demonstrated that LLM trading agents suffer from "epistemic hallucination" -- believing they hold positions they have already liquidated, creating "strategic paralysis" based on a phantom portfolio.

**Why it happens:** LLMs are trained to produce plausible text, not accurate financial analysis. They have no ground truth about current market state. When given market data, they can misinterpret numbers, confuse tickers, invert bullish/bearish signals, or generate analysis that sounds compelling but is factually wrong. Industry estimates attribute over $250M annually in losses to hallucination-related incidents in financial AI systems.

**Consequences:**
- Trades executed on fabricated analysis (e.g., LLM says "earnings beat expectations" when earnings missed)
- Position management errors from phantom portfolio state
- Cascading bad decisions as the hallucinated state compounds through the agent pipeline
- In TradeTrap testing: adaptive agents saw returns drop from 11.59% to 5.26% under data fabrication; state tampering caused 61% total losses

**Prevention:**
- NEVER let the LLM be the sole decision-maker. Use a neurosymbolic architecture: LLM provides reasoning/analysis, but deterministic code validates every factual claim and calculates every number
- All Greek calculations, position sizing, and P&L tracking must be done by deterministic quant code, not the LLM
- Implement a "reality check" layer: before any LLM recommendation reaches the executor, verify the referenced ticker exists, the stated price is within range of actual market data, and the described position matches the actual portfolio state
- Use structured output formats (JSON schemas) so LLM responses can be programmatically validated
- Log every LLM reasoning chain for post-hoc audit

**Detection:**
- LLM references a ticker/strike/expiry that does not exist in the contract database
- LLM states a position size or P&L that does not match the execution log
- LLM recommendation contradicts hard risk rules (e.g., "buy more" when position limit is hit)
- Divergence between LLM-described portfolio state and actual broker-reported state

**Phase:** Architecture must be designed for this in Phase 1. Validation layer built in Phase 2 (agent framework). Continuously hardened.

**Confidence:** HIGH -- TradeTrap paper provides rigorous experimental evidence; neurosymbolic approach recommended by multiple AI safety researchers.

---

### Pitfall 3: Multi-Agent Error Cascade (The 17x Amplification Trap)

**What goes wrong:** In a multi-agent pipeline (scanner -> strategist -> risk manager -> executor), each agent's output becomes the next agent's input. Errors do not cancel out -- they compound. Google DeepMind research (December 2025) found that unstructured multi-agent networks amplify errors up to 17.2x compared to single-agent baselines. Coordination failures account for 36.94% of all multi-agent system failures.

**Why it happens:** Teams build agents individually, test them individually, then chain them together assuming the pipeline will work. But agent-to-agent communication introduces: misinterpretation of certainty levels, race conditions on shared state (increasing quadratically with agent count), conflicting objectives between agents, and cascading failures where one bad output poisons all downstream decisions.

**Consequences:**
- Scanner identifies a false opportunity, strategist builds a position around it, risk manager approves it because the individual trade looks fine, executor places the order -- four agents all wrong in concert
- Race conditions where the risk manager checks limits before the executor's previous order has been acknowledged, leading to limit breaches
- Contradictory actions: one agent approving while another simultaneously blocking, creating undefined system state

**Prevention:**
- Use a centralized orchestrator (control plane) that suppresses error amplification, not a "bag of agents" where each agent freely passes messages to any other
- Define strict, schema-validated contracts between agents. Every inter-agent message must conform to a typed schema -- no free-text passing
- Implement checkpoint validation: after each agent in the pipeline, a deterministic validator checks the output before passing it to the next agent
- Build circuit breakers: if any agent in the chain produces output that fails validation, the entire pipeline halts for that opportunity (do not let partial state propagate)
- Maximum 3 retries per agent per workflow execution with exponential backoff
- Dead-letter queues for workflows that fail past the retry limit

**Detection:**
- Schema validation failures between agents
- Agent response time exceeding 2x normal (suggests it is struggling with bad input)
- Position or order state diverging between what the orchestrator believes and what IB reports
- Token consumption spiking (LLM agents consuming excessive tokens often indicates confusion/looping)

**Phase:** Agent communication architecture must be designed in Phase 1. Pipeline validation built in Phase 2. Circuit breakers in Phase 3 (risk management).

**Confidence:** HIGH -- Google DeepMind 17x finding is from rigorous multi-configuration testing; coordination failure statistics from MIT multi-agent research.

---

### Pitfall 4: Paper Trading Gives False Confidence for Options

**What goes wrong:** The system performs beautifully in paper trading, then hemorrhages money in live trading. IB's paper trading simulator has specific, documented limitations that make options backtesting unreliable: penny increments on US options are not supported (order fills but not at penny prices), fills are simulated from top of book only (no deep book), complex combo orders use a simplified simulator, and stops/complex order types are always simulated differently than live execution.

**Why it happens:** Options have wide bid-ask spreads, thin liquidity in OTM strikes, and complex execution dynamics that simulators cannot replicate. A strategy that "fills at the mid" in paper trading may only fill at the ask in live markets -- a difference that can turn a profitable strategy into a losing one. Options slippage can be 5-20% in illiquid strikes.

**Consequences:**
- Strategy that showed 15% annual return in paper trading loses money live due to fill slippage
- Position entry at worse prices means risk/reward ratios are wrong, stop losses trigger earlier
- False sense of system reliability leads to insufficient monitoring during early live trading
- Combo/spread orders that filled perfectly in paper may get legged (partial fills) in live, creating unintended naked positions

**Prevention:**
- Treat paper trading as a functional/integration test, NOT a profitability test. It verifies the plumbing works, not that the strategy makes money
- Build explicit slippage models: assume mid-market fills are impossible; model fills at 25-50% of the bid-ask spread from the unfavorable side
- For options specifically, check open interest and volume before any trade. If daily volume < 100 contracts or open interest < 500, assume slippage will eat your edge
- When transitioning to live: start with 10% of target position sizes for at least 2 weeks, comparing actual fills to what paper trading would have given
- Log actual vs. expected fill prices in live trading to build an empirical slippage model for your specific strategies

**Detection:**
- Actual fill prices consistently worse than paper trading fills
- Win rate in live trading more than 5% below paper trading win rate
- Average profit per trade in live is significantly less than paper projections
- Spread orders getting legged (one leg fills, other does not)

**Phase:** Awareness needed from Phase 1. Slippage modeling in Phase 3 (risk management). Paper-to-live transition protocol in Phase 5 (deployment).

**Confidence:** HIGH -- IB paper trading limitations from official IB documentation; slippage issues corroborated by multiple practitioner accounts and broker documentation.

---

### Pitfall 5: Options-Specific Risks That Automated Systems Routinely Mishandle

**What goes wrong:** Automated systems built by developers (rather than options traders) routinely fail to handle: early assignment on American-style options, pin risk at expiration, dividend-related assignment, automatic exercise by the OCC, and after-hours risk on expiration Friday.

**Why it happens:** Options are not stocks. They have nonlinear payoffs, time decay, multiple Greeks interacting simultaneously, and discontinuous events (assignment, exercise, expiration) that stock-focused trading systems have no analog for. Developers often treat options as "stocks with an expiry date" and get blindsided.

**Specific failure modes:**
- **Early assignment:** Short calls on dividend-paying stocks get assigned the night before ex-dividend. The system wakes up to find it is short 100 shares per contract with no hedging in place
- **Pin risk:** Stock closes at $100.00 on expiration, your $100 strike short options may or may not be assigned -- you do not know until Saturday, leaving you exposed to Monday gap risk on a potentially large stock position
- **After-hours exercise:** Options stop trading at 4:00 PM but stocks trade until 8:00 PM. An option that was OTM at 4:00 PM can become ITM by 4:30 PM and get exercised, or vice versa. The OCC auto-exercises options $0.01+ ITM based on the official close
- **Gamma risk near expiration:** Delta becomes extremely sensitive to price changes in the final days. A delta-neutral position can flip to heavily directional with a small move, causing losses that exceed what the risk system projected

**Prevention:**
- Build an expiration calendar into the system. Flag all positions entering the final 5 trading days
- Auto-close or roll positions with < 7 DTE (days to expiration) unless explicitly overridden by a human approval
- Before any short option position: check if the underlying pays a dividend and when the ex-date is. Block short calls on dividend-paying stocks within 5 days of ex-dividend unless the trade is explicitly a dividend play
- Monitor delta and gamma exposure at the portfolio level, not just per-position. Set portfolio-level gamma limits
- On expiration day: close all positions within $0.50 of the strike by 3:00 PM ET. Do not hold through close
- Handle assignment events explicitly in code: the system must have a handler that runs each morning to check for overnight assignments and update portfolio state before any new trades

**Detection:**
- Unexpected stock positions appearing in the account (assignment happened)
- Portfolio delta swinging wildly in final 3 DTE
- Margin requirements spiking unexpectedly (assigned stock positions require more margin than the original options)
- Position count mismatch between system state and broker state after overnight processing

**Phase:** Options-specific risk rules in Phase 3 (risk management). Expiration handling in Phase 4 (execution). Must be designed into the data model from Phase 1.

**Confidence:** HIGH -- Assignment mechanics from FINRA, OCC, and IB official documentation; expiration risks from multiple broker educational resources and options industry consensus.

---

### Pitfall 6: IB Connection Instability Causing Orphaned Orders and State Desynchronization

**What goes wrong:** The IB API connection drops (TWS/Gateway daily restart, internet blip, IB server reset), and the system either (a) loses track of open orders/positions, (b) re-sends orders that were already filled, or (c) misses fills that occurred during disconnection. Both TWS and IB Gateway are designed to be restarted daily, and IB performs server resets that disconnect all clients.

**Why it happens:** IB's infrastructure requires regular restarts. The TWS API uses a socket connection that can drop without warning. If the system does not have robust state reconciliation, it will diverge from reality after any disconnect. Critically: if you are logged into the Client Portal with the same username during a session, the API application cannot automatically reconnect after the next server reset.

**Consequences:**
- Duplicate orders: system re-sends an order post-reconnect, not knowing it already filled, doubling position size
- Orphaned orders: system places an order, disconnects before acknowledgment, the order fills at IB but the system does not know about it
- Missing stop-losses: protective orders that were attached to positions may need to be re-submitted after reconnection
- Portfolio state divergence: system thinks it has 5 positions, broker has 7 (from fills during disconnect)

**Prevention:**
- Use IB Gateway instead of TWS for production -- it consumes ~40% fewer resources and runs for longer periods
- Use IBC (IB Controller) for automated login, reconnection, and headless operation via virtual framebuffer
- Implement a "state reconciliation" routine that runs: (a) on every reconnection, (b) every 5 minutes during market hours, (c) before and after market open/close. This routine queries IB for all open orders and positions and reconciles against local state
- Use IB's `reqOpenOrders()` and `reqPositions()` as the source of truth, not local tracking
- Assign unique order IDs that survive reconnection (use the IB-provided `nextValidId` correctly)
- Never place an order without first confirming the connection is alive and the last reconciliation was recent
- Build for the IB daily restart window: schedule no trading during the expected restart period (typically around 11:45 PM - 12:45 AM ET Sunday through Friday)
- Do not log into Client Portal with the same username while the API is running

**Detection:**
- Connection status changes (monitor `connectionClosed` and `error` callbacks)
- Position count mismatch between local state and `reqPositions()` results
- Order IDs that the system does not recognize appearing in `openOrder` callbacks
- Unusual gaps in market data feed timestamps

**Phase:** Connection management and state reconciliation in Phase 1 (foundation/infrastructure). This is prerequisite infrastructure.

**Confidence:** HIGH -- IB official documentation confirms daily restart requirements, 50 msg/sec limit, Client Portal conflict, and connectionClosed callback behavior.

---

## Moderate Pitfalls

Mistakes that cause significant delays, technical debt, or degraded performance. Not immediately catastrophic but corrosive over time.

---

### Pitfall 7: Overfitting Strategies to Historical Data

**What goes wrong:** The LLM or quant models are trained/tuned on historical options data and produce strategies that exploit patterns specific to the training period. The strategies look brilliant in backtests (or even in the "analysis" phase of live trading) but fail systematically when market regime changes.

**Prevention:**
- Use walk-forward analysis, not static backtesting. Train on period A, validate on period B, then advance the window
- Test across multiple market regimes: bull, bear, low-vol, high-vol, rate-hiking, rate-cutting
- Apply a "haircut" to all backtest results: assume real performance will be 30-50% worse than backtest
- Set maximum strategy age: any strategy not validated in the last 30 days gets flagged for review
- The LLM should NEVER be shown full backtest results and asked "is this good?" -- it will confirm any pattern. Instead, use the LLM for qualitative market analysis and deterministic code for quantitative validation

**Detection:**
- Strategy Sharpe ratio in live trading is less than half of backtested Sharpe
- Strategy performance degrades monotonically over time (suggests overfitting to a regime that ended)
- Strategy only works on specific underlyings or specific days of the week (suggests data mining artifact)

**Phase:** Backtesting framework in Phase 2. Walk-forward validation in Phase 4.

**Confidence:** MEDIUM-HIGH -- overfitting is universally acknowledged in quantitative finance literature; specific haircut percentages are practitioner consensus rather than scientifically derived.

---

### Pitfall 8: Ignoring IB API Rate Limits and Throttling

**What goes wrong:** The system makes too many API calls, triggering throttling or disconnection. IB enforces: 50 messages/second to TWS, 10 requests/second on the Web API, 50 max concurrent historical data requests, no more than 6 identical requests for the same contract/exchange/tick type within 2 seconds, and max 60 historical data requests per 10-minute window. BID_ASK historical requests count as TWO requests. Exceeding historical data limits leads to throttling and eventual disconnection.

**Prevention:**
- Implement a message queue with rate limiting at the API gateway layer. Never allow agents to make raw API calls
- For options chain lookups: use `reqSecDefOptParams()` (introduced in v9.72) instead of `reqContractDetails()`. The latter with an incomplete options contract can return thousands of results and break the connection
- Cache contract details, option chains, and historical data. Options contract IDs (conIds) are static and never change -- cache them permanently
- Batch market data requests. Request streaming data (`reqMktData`) for instruments you monitor continuously rather than polling
- For historical data: implement a request queue with built-in pacing that respects the 15-second same-request rule and the 6-per-2-second rule
- The Web API global limit of 10 req/sec per username is separate from TWS API limits -- plan accordingly if using both

**Detection:**
- Error codes from IB indicating pacing violation
- Historical data requests timing out (exceeding several minutes means you should cancel via `cancelHistoricalData()`)
- Sudden market data gaps indicating throttling or disconnect
- API log showing "Max messages per second" warnings

**Phase:** API abstraction layer with rate limiting in Phase 1 (foundation). Must be designed into the architecture from the start.

**Confidence:** HIGH -- all limits from IB official TWS API documentation (order_limitations.html, historical_limitations.html).

---

### Pitfall 9: Stale Volatility Data Leading to Mispriced Trades

**What goes wrong:** Options prices are driven by implied volatility, which changes continuously. An automated system that caches or delays volatility data makes decisions on stale information. A volatility surface built at 10:00 AM can be meaningfully wrong by 2:00 PM if the underlying moves 2-3%. Illiquid OTM options may have last-trade prices that are hours old and no longer reflect reality.

**Prevention:**
- Never use last-trade price for options -- use live bid/ask midpoint with a freshness check. If the quote is more than 30 seconds old for liquid options (or 5 minutes for illiquid), flag it as stale
- Check bid-ask spread width before trading. Normal near-term ATM options have ~2 vol point spreads; 10+ vol point spreads in OTM weeklies signal unreliable quotes
- Filter out options with zero volume AND wide markets (>$0.50 spread on sub-$5 options) from the tradeable universe
- If building a volatility surface: implement consistency guards that reject interpolation when IV spreads between neighboring strikes/expiries are too wide
- Refresh Greek calculations in real-time using streaming market data, not periodic snapshots
- Be especially cautious around earnings, FOMC, and other high-vol events where surfaces can shift dramatically intraday

**Detection:**
- Greeks-based risk limits triggering unexpectedly (suggests stale Greek values)
- Filled prices significantly different from model-predicted fair value
- Large discrepancy between model-implied IV and broker-reported IV
- Options position showing profit at stale prices but loss at refreshed prices

**Phase:** Market data infrastructure in Phase 2. IV surface management in Phase 3 (strategy/risk).

**Confidence:** MEDIUM-HIGH -- academic research (ICML 2025) confirms real-time IV computation challenges; practitioner sources confirm stale data risks.

---

### Pitfall 10: Margin Requirement Surprises and Forced Liquidation

**What goes wrong:** IB calculates margin requirements in real-time and will auto-liquidate positions if the account falls below maintenance margin. Options margin is complex and can change dramatically: a short put that required $2,000 margin can suddenly require $10,000 if the underlying drops 5%. Assignment overnight can convert options positions to stock positions with completely different margin requirements.

**Prevention:**
- Never use more than 50% of available margin for automated trading. The other 50% is a buffer for adverse moves and margin requirement increases
- Calculate worst-case margin requirements, not current margin. Model what happens if all underlyings move 2 standard deviations adversely simultaneously
- Check margin impact BEFORE placing orders using IB's `reqMarginChanges()` or `whatIfOrder()` to get the margin impact of a hypothetical order
- Build margin monitoring into the risk manager: alert at 60% utilization, halt new positions at 70%, start reducing positions at 80%
- Account for the fact that margin requirements can change without any trade -- just from underlying price movement, volatility changes, or IB policy updates

**Detection:**
- Margin utilization exceeding 60% (yellow alert)
- Margin utilization exceeding 75% (red alert, halt new positions)
- Sudden margin spikes on unchanged portfolio (indicates underlying moved or IB changed requirements)
- IB margin warning messages in API callbacks

**Phase:** Margin monitoring in Phase 3 (risk management). Pre-trade margin checks in Phase 4 (execution).

**Confidence:** HIGH -- IB margin documentation is authoritative; auto-liquidation behavior confirmed by IB official docs and multiple user reports.

---

### Pitfall 11: Inadequate Audit Trail and Observability

**What goes wrong:** The system makes trades, but when something goes wrong (or when you need to understand why a specific trade was made), there is no way to reconstruct the decision chain. This matters for debugging, for strategy improvement, and potentially for regulatory compliance. SEC/FINRA requires firms to maintain records of automated trading decisions.

**Prevention:**
- Log the COMPLETE decision chain for every trade: scanner signal -> strategist analysis -> risk assessment -> execution decision -> order details -> fill confirmation
- Include the LLM's full reasoning (prompt + completion) in the audit log -- not just the final decision
- Store all logs in an append-only store (not a database that can be modified)
- Include timestamps, market data snapshots at decision time, and the specific version of each agent/model that produced the output
- Build a "trade replay" capability: given a trade ID, reconstruct exactly what data the system saw and why it made each decision
- Retain logs for at least 6 years (SEC regulatory requirement for broker-dealers; good practice even for personal trading)

**Detection:**
- Cannot explain why a specific trade was made when reviewing
- Post-mortem analysis blocked by missing data
- Discrepancy between what the system log says and what actually happened at the broker

**Phase:** Logging infrastructure in Phase 1. Full decision chain logging in Phase 2 (agent framework). Trade replay in Phase 4.

**Confidence:** MEDIUM -- regulatory requirements apply to broker-dealers and may not strictly apply to personal trading, but the engineering benefits of full audit trails are universally acknowledged. SEC/FINRA record-keeping requirements are well-documented for firms.

---

## Minor Pitfalls

Mistakes that cause annoyance, wasted time, or minor financial impact. Fixable, but better to avoid.

---

### Pitfall 12: Contract Specification Errors in Options Orders

**What goes wrong:** Options contracts require precise specification: underlying, expiry date, strike price, right (call/put), multiplier, and exchange. Getting any of these wrong results in either a rejected order or -- worse -- a fill on the wrong contract. IB's contract system uses conIds as the primary identifier, and some combinations of strike and expiry do not correspond to valid contracts.

**Prevention:**
- Always resolve to a conId before placing orders. Use `reqSecDefOptParams()` to get the valid option chain, then select from valid contracts only
- Cache the full option chain with conIds. ConIds are static and permanent (e.g., AAPL stock is always conId 265598)
- Validate multiplier (usually 100, but not always -- some index options, mini options, and adjusted contracts have different multipliers)
- Enforce minimum 1-second intervals between `reqMatchingSymbols()` calls (IB requirement)
- Build a contract validation layer that rejects any order where the contract cannot be confirmed against the cached chain

**Phase:** Contract management in Phase 1 (foundation/data layer).

**Confidence:** HIGH -- IB official API documentation.

---

### Pitfall 13: Over-Engineering the Multi-Agent System

**What goes wrong:** Teams build elaborate multi-agent systems with 6+ specialized agents, complex negotiation protocols, and sophisticated inter-agent communication, when a simpler 3-4 agent pipeline with a strong orchestrator would perform better. Research shows multi-agent systems frequently perform WORSE than single-agent systems when the coordination overhead exceeds the benefit of specialization.

**Prevention:**
- Start with the minimum viable agent count: scanner, risk manager, executor. Add a strategist only when the simpler pipeline demonstrably lacks capability
- Use deterministic code (not agents) for anything that has a clear algorithm: risk limit checks, position sizing, margin calculations, order routing
- Reserve LLM agents for tasks that genuinely benefit from reasoning: market narrative analysis, unusual event interpretation, strategy selection from a pre-approved menu
- Measure agent count against the DeepMind finding: with N agents, you have N(N-1)/2 potential race conditions. At 4 agents that is 6; at 6 agents it is 15; at 8 agents it is 28

**Phase:** Architecture decision in Phase 1. Resist the temptation to add agents in later phases without clear justification.

**Confidence:** MEDIUM-HIGH -- "multi-agent trap" documented in multiple sources including Towards Data Science analysis of DeepMind findings.

---

### Pitfall 14: Market Data Subscription Cost Surprises

**What goes wrong:** IB charges for real-time market data subscriptions, and options data is particularly expensive. Teams build systems assuming data will be available, then discover they need: US Securities Snapshot & Futures Value Bundle, US Equity and Options Add-On Streaming Bundle, and possibly exchange-specific feeds. Paper trading uses the same data subscriptions as the live account.

**Prevention:**
- Audit data requirements before building. List every data type needed (equity quotes, option chains, Greeks, historical data) and map to IB subscription packages
- You cannot run real-time paper and live simultaneously on different machines with the same data subscription
- Consider delayed data (15 min) for non-time-sensitive scanning, reserving real-time for execution
- Budget $30-100/month minimum for US options data feeds

**Phase:** Discovery in Phase 1. Budget allocation before development begins.

**Confidence:** MEDIUM -- specific subscription packages and pricing change; the general principle that IB charges for data is well-documented.

---

### Pitfall 15: Treating the Human Approval Loop as an Afterthought

**What goes wrong:** The system is designed for full autonomy, and the "human approval for large trades" feature is bolted on later. This results in a poor UX where the human either rubber-stamps everything (defeating the purpose) or is overwhelmed with approval requests and starts ignoring them.

**Prevention:**
- Design the approval workflow from the start. Every trade recommendation should include: why (reasoning summary), what (exact order details), risk (maximum loss scenario), and urgency (how long before the opportunity expires)
- Implement tiered autonomy with clear thresholds: e.g., trades < $500 max risk auto-execute, $500-$2000 notify but execute, > $2000 require explicit approval
- Make the approval UI show the trade in context: current portfolio, how this changes Greeks exposure, correlation with existing positions
- Build a "timeout" for approval requests: if not approved within N minutes, the opportunity expires and the system moves on. Never queue stale trade recommendations
- Track approval/rejection patterns to calibrate autonomy thresholds over time

**Phase:** Approval workflow design in Phase 2 (agent framework). UI implementation in Phase 4 (dashboard).

**Confidence:** MEDIUM -- this is informed by UX best practices and multi-agent system design patterns rather than documented failures, but the principle is well-established in human-in-the-loop AI systems.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|---|---|---|
| Foundation / Infrastructure | IB connection instability (Pitfall 6), no kill switch (Pitfall 1), API rate limits (Pitfall 8) | Build connection management, kill switch, and rate limiting FIRST. These are prerequisites, not features |
| Agent Framework | Error cascade (Pitfall 3), LLM hallucination (Pitfall 2), over-engineering (Pitfall 13) | Centralized orchestrator with schema-validated contracts; deterministic validation after every LLM output; start with minimal agents |
| Risk Management | Options-specific risks (Pitfall 5), margin surprises (Pitfall 10), position sizing errors | Implement Greeks-aware risk limits, expiration calendar, assignment handlers, margin monitoring |
| Strategy / Backtesting | Overfitting (Pitfall 7), stale volatility data (Pitfall 9), paper trading false confidence (Pitfall 4) | Walk-forward analysis, slippage models, treat paper as integration test only |
| Execution / Live Trading | Fill slippage, connection drops during execution, partial fills on spreads | Reconciliation routines, order state machine, spread order protection |
| Dashboard / Monitoring | Inadequate observability (Pitfall 11), human approval UX (Pitfall 15) | Full decision chain logging from day 1; design approval workflow before building UI |

---

## Meta-Pitfall: The Sequencing Trap

The most dangerous meta-pitfall in this domain is building the "exciting" parts first (LLM analysis, strategy generation, multi-agent coordination) before the "boring" parts (kill switch, state reconciliation, risk limits, connection management). Every catastrophic failure in automated trading history -- Knight Capital, the Flash Crash, individual account blow-ups -- came from insufficient safety infrastructure, not insufficient intelligence.

**The correct sequencing is:**
1. Safety infrastructure (kill switch, risk limits, connection management)
2. Data infrastructure (market data, contract management, state tracking)
3. Execution infrastructure (order management, reconciliation, fill tracking)
4. Intelligence layer (LLM agents, strategy, scanning)

This is the opposite of what feels natural. It means the system cannot do anything interesting for the first 2-3 phases. That is correct. A trading system that cannot trade safely should not trade at all.

---

## Sources

### Academic / Research
- [TradeTrap: Are LLM-based Trading Agents Truly Reliable and Faithful?](https://arxiv.org/html/2512.02261v1) -- LLM trading agent failure modes (HIGH confidence)
- [Why Do Multi-Agent LLM Systems Fail?](https://arxiv.org/html/2503.13657v1) -- Multi-agent coordination failures, 17x error amplification (HIGH confidence)
- [Systemic Failures in Algorithmic Trading](https://pmc.ncbi.nlm.nih.gov/articles/PMC8978471/) -- Knight Capital analysis, tight coupling in automated markets (HIGH confidence)
- [From Spark to Fire: Error Cascades in LLM Multi-Agent Collaboration](https://arxiv.org/abs/2603.04474) -- Cascade amplification, topological sensitivity (HIGH confidence)

### Interactive Brokers Official Documentation
- [TWS API Order Limitations](https://interactivebrokers.github.io/tws-api/order_limitations.html) -- 50 msg/sec, 20 active orders per contract per side (HIGH confidence)
- [TWS API Historical Data Limitations](https://interactivebrokers.github.io/tws-api/historical_limitations.html) -- Pacing rules, concurrent request limits (HIGH confidence)
- [TWS API Options](https://interactivebrokers.github.io/tws-api/options.html) -- reqSecDefOptParams, contract specification (HIGH confidence)
- [IB Paper Trading vs Live Trading](https://www.interactivebrokers.com/campus/trading-lessons/paper-trading-vs-live-trading-whats-the-difference/) -- Simulator limitations (HIGH confidence)
- [IB Options Margin Requirements](https://www.interactivebrokers.com/en/trading/margin-options.php) -- Real-time margin, auto-liquidation (HIGH confidence)
- [IB Gateway](https://www.interactivebrokers.com/en/trading/ibgateway-stable.php) -- Resource usage, stability comparison (HIGH confidence)
- [IB Exercise and Assignment](https://www.interactivebrokers.com/campus/trading-lessons/exercise-and-assignment/) -- Assignment mechanics (HIGH confidence)

### Industry / Practitioner
- [Knight Capital Case Study](https://www.henricodolfing.ch/en/case-study-4-the-440-million-software-error-at-knight-capital/) -- $440M loss analysis (HIGH confidence)
- [Why Most Trading Bots Lose Money](https://www.fortraders.com/blog/trading-bots-lose-money) -- 52% failure rate in 3 months (MEDIUM confidence)
- [The Multi-Agent Trap](https://towardsdatascience.com/the-multi-agent-trap/) -- Over-engineering multi-agent systems (MEDIUM confidence)
- [FINRA Options Assignment](https://www.finra.org/investors/insights/trading-options-understanding-assignment) -- Assignment rules and risks (HIGH confidence)
- [IBC - IB Controller](https://github.com/IbcAlpha/IBC) -- Headless IB Gateway automation (MEDIUM confidence)
- [Automated Trading Architecture Patterns](https://dev.to/jungle_sven/simple-yet-effective-architecture-patterns-for-algorithmic-trading-5745) -- Event-driven architecture (MEDIUM confidence)
