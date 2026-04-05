# Phase 8: Alerts & Autonomy - Research

**Researched:** 2026-04-05
**Domain:** Alert routing (Slack/SMS), autonomous trade execution with threshold gating, and human-in-the-loop approval workflows
**Confidence:** HIGH

## Summary

Phase 8 introduces three capabilities: (1) an alert routing system that sends real-time notifications via Slack webhooks and Twilio SMS for trade executions, risk limit breaches, and system errors; (2) a threshold-based auto-execute gate in the pipeline that routes small trades directly to the executor and escalates large trades for human approval; and (3) a human approval workflow with interactive Slack buttons, a dashboard approval UI, and a safe timeout-to-reject default.

The architecture integrates cleanly with the existing Redis pub/sub event infrastructure (Phase 2 dual-write pattern). A new `AlertRouter` consumes Redis pub/sub events and fans them out to Slack and SMS channels. The approval workflow introduces a new pipeline node between the risk manager and executor that holds trades pending human decision, using Redis for approval state and `asyncio.wait_for()` for timeout enforcement.

For Slack interactive buttons (approve/reject from Slack), the system needs `slack-bolt` running in Socket Mode. Socket Mode uses a WebSocket connection from the app to Slack, eliminating the need for a public HTTP endpoint -- ideal for a trading system running behind a firewall. The same Slack app can both send alert messages (via `slack_sdk.webhook.AsyncWebhookClient`) and receive button interaction payloads (via `slack-bolt` Socket Mode).

**Primary recommendation:** Use `slack-bolt[async]` with Socket Mode for bidirectional Slack integration (outgoing alerts via webhook + incoming button clicks via WebSocket), `httpx` for Twilio SMS HTTP calls (lighter than the full `twilio` SDK; this system only needs SMS send), Redis pub/sub for event consumption, and `asyncio.wait_for()` for approval timeout enforcement. The approval gate should be a new LangGraph conditional node between risk_manager and executor.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| slack-bolt | >=1.27.0 | Slack app framework with Socket Mode for interactive buttons | Official Slack framework; handles action ack(), button payloads, token rotation, rate limiting |
| slack-sdk | >=3.41.0 | AsyncWebhookClient for outgoing alert messages | Official Slack SDK; AsyncWebhookClient for non-blocking webhook POSTs; dependency of slack-bolt |
| httpx | >=0.28.1 | Async HTTP client for Twilio SMS API calls | Lighter than full twilio SDK; requests-like API; async native; only need one POST endpoint |
| aiohttp | >=3.9.0 | Required by slack-bolt async Socket Mode adapter | Dependency of slack-bolt[async]; also used by slack-sdk AsyncWebClient |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| twilio | >=9.0.0 | Full Twilio SDK (alternative to httpx) | Only if SMS features grow beyond simple send (e.g., delivery status webhooks, phone number lookup) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| slack-bolt Socket Mode | HTTP Request URL (ngrok/public endpoint) | Requires public endpoint; Socket Mode is zero-infrastructure for behind-firewall apps |
| httpx for Twilio | Full twilio SDK | twilio SDK is 10MB+, adds aiohttp dependency for async; httpx is already used and only 1 API call needed |
| httpx for Twilio | aiohttp directly | aiohttp already required by slack-bolt; but httpx has cleaner request-style API for simple POSTs |
| Redis pub/sub for events | Direct function calls | Redis pub/sub decouples alert routing from trade execution; already established pattern |
| asyncio.wait_for() | APScheduler/Celery for timeouts | Over-engineered; native asyncio is sufficient for single-process timeout |

**Installation (Backend):**
```bash
# Add to pyproject.toml dependencies
uv add "slack-bolt>=1.27.0" "slack-sdk>=3.41.0" "httpx>=0.28.1"
# aiohttp comes as dependency of slack-bolt[async]
```

**No frontend installation needed for 08-01 through 08-03.** The dashboard approval UI (08-04) uses the existing Next.js + shadcn/ui stack from Phase 7.

## Architecture Patterns

### Recommended Project Structure
```
src/trading/
├── alerts/                  # NEW: Phase 8 alert system
│   ├── __init__.py
│   ├── config.py            # AlertConfig, threshold config, Slack/SMS credentials
│   ├── router.py            # AlertRouter: Redis subscriber -> fan-out to channels
│   ├── slack.py             # SlackNotifier: webhook alerts + Block Kit message builders
│   ├── sms.py               # SMSNotifier: Twilio SMS via httpx
│   └── approval.py          # ApprovalManager: pending trade state, timeout, resolve
├── agents/
│   ├── pipeline.py          # MODIFIED: add approval gate node between risk & executor
│   └── ...
├���─ dashboard/
│   ├── routes/
│   │   └── approvals.py     # NEW: REST endpoints for approval UI
│   └── ...
└── ...

dashboard/src/
├── app/approvals/page.tsx   # NEW: approval queue page
├── components/approvals/    # NEW: approval card, trade context display
├── stores/approvals-store.ts # NEW: Zustand store for pending approvals
└── ...
```

### Pattern 1: Event-Driven Alert Routing via Redis Pub/Sub
**What:** AlertRouter subscribes to Redis pub/sub channels for trade events, risk events, and system errors, then fans out to Slack and SMS notifiers based on event severity and user configuration.
**When to use:** All alert-worthy events -- trade executions, risk limit breaches, circuit breaker activations, system errors, approval requests, approval timeouts.
**Example:**
```python
# Source: Established project pattern (Phase 2 dual-write, Phase 7 RedisBridge)
class AlertRouter:
    """Consumes Redis pub/sub events and routes to notification channels."""

    CHANNELS = [
        "alerts:trade_executed",
        "alerts:trade_rejected",
        "alerts:risk_breach",
        "alerts:circuit_breaker",
        "alerts:system_error",
        "alerts:approval_request",
        "alerts:approval_resolved",
    ]

    def __init__(
        self,
        redis: Redis,
        slack_notifier: SlackNotifier | None,
        sms_notifier: SMSNotifier | None,
        config: AlertConfig,
    ) -> None:
        self._redis = redis
        self._slack = slack_notifier
        self._sms = sms_notifier
        self._config = config

    async def listen(self) -> None:
        """Subscribe to alert channels and route to notifiers."""
        pubsub = self._redis.pubsub()
        await pubsub.psubscribe(*self.CHANNELS)

        async for message in pubsub.listen():
            if message["type"] != "pmessage":
                continue
            channel = message["channel"]
            data = json.loads(message["data"])
            await self._route(channel, data)

    async def _route(self, channel: str, data: dict) -> None:
        """Route event to appropriate notification channels."""
        if self._slack and self._config.slack_enabled:
            await self._slack.send(channel, data)
        if self._sms and self._config.sms_enabled:
            # SMS only for high-severity: risk breaches, system errors
            if channel in self._config.sms_channels:
                await self._sms.send(channel, data)
```

### Pattern 2: Threshold-Based Approval Gate in Pipeline
**What:** A new conditional routing point in the LangGraph pipeline that checks trade size/Greeks impact against configurable thresholds. Below-threshold trades auto-execute; above-threshold trades are held pending human approval.
**When to use:** After risk_manager approves a trade, before executor submits it.
**Example:**
```python
# Source: Existing pipeline pattern (route_after_scan, route_after_risk)
def route_after_risk(state: PipelineState) -> str:
    """Route approved trades through approval gate or direct to executor."""
    approved = [a for a in state.get("risk_assessments", [])
                if a.get("approved", False)]
    if not approved:
        return END

    # Check if any approved trade exceeds auto-execute threshold
    needs_approval = any(
        _exceeds_threshold(a, state) for a in approved
    )
    if needs_approval:
        return "approval_gate"
    return "executor"

def _exceeds_threshold(assessment: dict, state: PipelineState) -> bool:
    """Check if a trade exceeds auto-execute thresholds."""
    proposal = _find_proposal(assessment, state["trade_proposals"])
    if not proposal:
        return True  # Safe default: require approval if unknown
    config = state.get("auto_execute_config", {})
    if abs(proposal.get("max_loss", 0)) > config.get("max_loss_dollars", 500):
        return True
    # Check Greeks impact thresholds...
    return False
```

### Pattern 3: Approval Workflow with Timeout-to-Reject
**What:** Pending approvals are stored in Redis with an async timeout. If no human response within the configured timeout, the trade is automatically rejected (safe default). The approval state machine has three terminal states: approved, rejected, timed_out.
**When to use:** For every trade that exceeds the auto-execute threshold.
**Example:**
```python
# Source: Python asyncio docs, project Redis patterns
class ApprovalManager:
    """Manages pending trade approvals with timeout-to-reject."""

    def __init__(self, redis: Redis, timeout_seconds: int = 300) -> None:
        self._redis = redis
        self._timeout = timeout_seconds
        self._pending: dict[str, asyncio.Future] = {}

    async def request_approval(self, approval_id: str, context: dict) -> str:
        """Create approval request and wait for response or timeout.

        Returns: "approved", "rejected", or "timed_out"
        """
        # Store in Redis for dashboard/Slack visibility
        await self._redis.hset(f"approval:{approval_id}", mapping={
            "status": "pending",
            "context": json.dumps(context),
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "timeout_at": (datetime.now(timezone.utc) +
                          timedelta(seconds=self._timeout)).isoformat(),
        })
        # Publish for alert routing
        await self._redis.publish("alerts:approval_request",
                                  json.dumps({"approval_id": approval_id, **context}))

        # Wait for resolution or timeout
        future: asyncio.Future[str] = asyncio.get_event_loop().create_future()
        self._pending[approval_id] = future

        try:
            result = await asyncio.wait_for(future, timeout=self._timeout)
            return result
        except asyncio.TimeoutError:
            await self._resolve(approval_id, "timed_out")
            return "timed_out"

    async def resolve(self, approval_id: str, decision: str) -> None:
        """Resolve a pending approval (called from Slack button or dashboard)."""
        future = self._pending.get(approval_id)
        if future and not future.done():
            future.set_result(decision)
        await self._resolve(approval_id, decision)

    async def _resolve(self, approval_id: str, decision: str) -> None:
        """Update Redis state and publish resolution event."""
        await self._redis.hset(f"approval:{approval_id}", mapping={
            "status": decision,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        })
        await self._redis.publish("alerts:approval_resolved",
                                  json.dumps({"approval_id": approval_id,
                                             "decision": decision}))
        self._pending.pop(approval_id, None)
```

### Pattern 4: Slack Interactive Buttons via Socket Mode
**What:** A `slack-bolt` AsyncApp running in Socket Mode that receives button click payloads for approve/reject actions without requiring a public HTTP endpoint. Runs as a background task alongside the main trading app.
**When to use:** For the Slack approve/reject buttons on escalated trade messages.
**Example:**
```python
# Source: Slack Bolt docs, Socket Mode docs
from slack_bolt.app.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

app = AsyncApp(token=os.environ["SLACK_BOT_TOKEN"])

@app.action("approve_trade")
async def handle_approve(ack, body, client):
    await ack()
    approval_id = body["actions"][0]["value"]
    await approval_manager.resolve(approval_id, "approved")
    # Update the Slack message to show approval
    await client.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        blocks=_build_resolved_blocks(approval_id, "approved"),
    )

@app.action("reject_trade")
async def handle_reject(ack, body, client):
    await ack()
    approval_id = body["actions"][0]["value"]
    await approval_manager.resolve(approval_id, "rejected")
    await client.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        blocks=_build_resolved_blocks(approval_id, "rejected"),
    )

# Start as background task in TradingApp
async def start_slack_bot():
    handler = AsyncSocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    await handler.start_async()
```

### Pattern 5: Block Kit Message for Trade Approval
**What:** Rich Slack messages using Block Kit with trade context (strategy, Greeks impact, max loss, P&L scenario) and interactive approve/reject buttons.
**When to use:** For every escalated trade approval request.
**Example:**
```python
# Source: Slack Block Kit docs
def build_approval_blocks(approval_id: str, context: dict) -> list[dict]:
    """Build Slack Block Kit blocks for trade approval message."""
    return [
        {"type": "header", "text": {"type": "plain_text",
         "text": "Trade Approval Required"}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Symbol:* {context['symbol']}"},
            {"type": "mrkdwn", "text": f"*Strategy:* {context['strategy_type']}"},
            {"type": "mrkdwn", "text": f"*Max Loss:* ${context['max_loss']:,.2f}"},
            {"type": "mrkdwn", "text": f"*Max Profit:* ${context['max_profit']:,.2f}"},
        ]},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Delta Impact:* {context.get('delta', 0):.2f}"},
            {"type": "mrkdwn", "text": f"*Theta Impact:* {context.get('theta', 0):.2f}"},
            {"type": "mrkdwn", "text": f"*Vega Impact:* {context.get('vega', 0):.2f}"},
            {"type": "mrkdwn", "text": f"*Timeout:* {context['timeout_minutes']}m"},
        ]},
        {"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "Approve"},
             "style": "primary", "action_id": "approve_trade",
             "value": approval_id},
            {"type": "button", "text": {"type": "plain_text", "text": "Reject"},
             "style": "danger", "action_id": "reject_trade",
             "value": approval_id},
        ]},
    ]
```

### Anti-Patterns to Avoid
- **Approval state in memory only:** If the process restarts, pending approvals are lost. Store approval state in Redis with TTL so the dashboard can display them even after restart.
- **Blocking the pipeline on approval:** The approval gate must not block other pipeline runs. Use `asyncio.Future` per approval, not a global lock.
- **Sending SMS for every event:** SMS is expensive and rate-limited. Reserve for high-severity events (circuit breaker, system errors). Use Slack for routine trade alerts.
- **Hardcoded thresholds:** Auto-execute thresholds must be configurable via YAML config, not hardcoded. Different paper/live thresholds (like risk limits).
- **No ack() on Slack actions:** Slack requires acknowledgment within 3 seconds. Always call `ack()` first, then do async work. Failure to ack results in "This action didn't work" error.
- **Public HTTP endpoint for Slack:** Socket Mode eliminates the need for ngrok or a public URL. Do not set up HTTP request URL when Socket Mode is available.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Slack message formatting | Custom JSON builders | Slack Block Kit (dict structures) | Block Kit has section, header, actions blocks with validated structure; complex layouts are error-prone to hand-roll |
| Slack action handling | Custom WebSocket listener for Slack | slack-bolt AsyncApp with @app.action() | Bolt handles payload verification, token rotation, rate limiting, retry logic |
| Socket Mode connection | Raw WebSocket to Slack | AsyncSocketModeHandler | Handles connection lifecycle, reconnects, URL refresh (Socket Mode URLs are not static) |
| Timeout-to-reject | Background thread with sleep | asyncio.wait_for() on Future | Native asyncio; handles cancellation correctly; integrates with event loop |
| SMS delivery | Raw HTTP to Twilio API | httpx.AsyncClient POST with auth | httpx handles connection pooling, retries, TLS; Twilio REST API is a single POST |

**Key insight:** The Slack interaction surface (Socket Mode + Block Kit + action handlers) has significant protocol complexity (payload signing, acknowledgment deadlines, connection lifecycle) that slack-bolt abstracts away. Hand-rolling this is weeks of work and fragile.

## Common Pitfalls

### Pitfall 1: Slack 3-Second Acknowledgment Deadline
**What goes wrong:** Slack requires action acknowledgment within 3 seconds. If your handler does database work or external API calls before ack(), the user sees "This action didn't work."
**Why it happens:** Developers put business logic before the ack() call.
**How to avoid:** Always call `await ack()` as the first line of every action handler. Do async work after acknowledging.
**Warning signs:** Users report intermittent "action didn't work" errors on Slack buttons.

### Pitfall 2: Socket Mode Connection Limits
**What goes wrong:** Slack limits Socket Mode to 10 concurrent WebSocket connections per app. If your app creates multiple connections (e.g., multiple processes), you hit the limit.
**Why it happens:** Running multiple instances of the Slack bot process.
**How to avoid:** Run exactly one Socket Mode handler as a singleton background task. The trading system is a single process, so this is natural.
**Warning signs:** Connection failures with "too many connections" errors in logs.

### Pitfall 3: Approval State Lost on Restart
**What goes wrong:** If approval state is only in memory (asyncio.Future dict), a process restart loses all pending approvals. Trades hang in limbo.
**Why it happens:** Not persisting approval state to Redis/DB.
**How to avoid:** Store full approval context in Redis with TTL. On startup, scan for expired approvals and auto-reject them (safe default). The in-memory Future is for the current process; Redis is the source of truth.
**Warning signs:** After restart, dashboard shows "pending" approvals that will never resolve.

### Pitfall 4: Threshold Config Not Separated by Paper/Live
**What goes wrong:** Paper trading uses the same auto-execute thresholds as live, meaning either paper is too restrictive or live is too permissive.
**Why it happens:** Single threshold config without mode awareness.
**How to avoid:** Follow the established `RiskLimitsConfig` pattern with separate `paper` and `live` profiles for auto-execute thresholds.
**Warning signs:** Constant approval prompts in paper mode, or trades auto-executing in live that shouldn't.

### Pitfall 5: Twilio Rate Limiting and Cost
**What goes wrong:** A flurry of events (e.g., multiple risk breaches in quick succession) triggers many SMS messages, hitting Twilio rate limits or running up costs.
**Why it happens:** No deduplication or rate limiting on the SMS notifier.
**How to avoid:** Implement per-channel cooldown in SMSNotifier (e.g., no more than 1 SMS per event type per 5 minutes). Use Redis for cooldown tracking with TTL keys.
**Warning signs:** Twilio billing spikes; "too many requests" errors in logs.

### Pitfall 6: Approval Timeout Mismatch Between Systems
**What goes wrong:** The Slack message says "5 min timeout" but the actual asyncio timeout is different, or the Redis TTL doesn't match.
**Why it happens:** Timeout value defined in multiple places without a single source of truth.
**How to avoid:** Store timeout_seconds in the approval config once. Derive the Slack message text, asyncio timeout, and Redis TTL all from this single value.
**Warning signs:** Trades auto-rejected before the displayed timeout, or Slack buttons still active after timeout.

### Pitfall 7: Pipeline Deadlock on Approval
**What goes wrong:** The LangGraph pipeline blocks waiting for approval, preventing the next scheduled pipeline run.
**Why it happens:** The approval gate node awaits the Future synchronously within the graph execution.
**How to avoid:** The approval gate should store the pending state and return a "pending_approval" status in PipelineState. A separate async task monitors approval resolution and, when resolved, either re-invokes the executor or marks the run as rejected. Alternatively, split the pipeline into two phases: pre-approval and post-approval.
**Warning signs:** Pipeline runs queue up behind a pending approval; scheduled scans are missed.

## Code Examples

Verified patterns from official sources and existing project code:

### Slack Webhook Alert (Outgoing Only)
```python
# Source: slack-sdk docs (https://slack.dev/python-slack-sdk/webhook/index.html)
from slack_sdk.webhook.async_client import AsyncWebhookClient

async def send_slack_alert(webhook_url: str, text: str, blocks: list | None = None):
    """Send an alert message to Slack via incoming webhook."""
    client = AsyncWebhookClient(webhook_url)
    response = await client.send(text=text, blocks=blocks)
    if response.status_code != 200:
        log.warning("slack_alert.failed", status=response.status_code)
```

### Twilio SMS via httpx
```python
# Source: Twilio REST API docs (https://www.twilio.com/docs/messaging/quickstart)
import httpx

async def send_sms(
    account_sid: str,
    auth_token: str,
    from_number: str,
    to_number: str,
    body: str,
) -> dict:
    """Send SMS via Twilio REST API using httpx."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json",
            auth=(account_sid, auth_token),
            data={"To": to_number, "From": from_number, "Body": body},
        )
        response.raise_for_status()
        return response.json()
```

### Redis Event Publishing for Alerts
```python
# Source: Existing project pattern (DashboardPublisher, RedisDistributor)
async def publish_trade_alert(redis: Redis, event_type: str, data: dict) -> None:
    """Publish a trade event to the alert channel."""
    channel = f"alerts:{event_type}"
    payload = json.dumps({
        **data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    # Dual-write: SET for snapshot, PUBLISH for real-time
    await redis.set(f"alert:latest:{event_type}", payload, ex=3600)
    await redis.publish(channel, payload)
```

### Config Pattern for Alert Thresholds
```python
# Source: Existing RiskLimitsConfig pattern (trading.risk.config)
class AutoExecuteThresholds(BaseModel):
    """Thresholds below which trades auto-execute without approval."""
    max_loss_dollars: float = Field(default=500.0, gt=0)
    max_delta_impact: float = Field(default=50.0, gt=0)
    max_vega_impact: float = Field(default=100.0, gt=0)
    approval_timeout_seconds: int = Field(default=300, gt=30, le=3600)

class AlertConfig(BaseModel):
    """Alert and autonomy configuration."""
    slack_enabled: bool = False
    slack_webhook_url: str = ""
    slack_bot_token: str = ""      # xoxb-* for Socket Mode
    slack_app_token: str = ""      # xapp-* for Socket Mode
    slack_channel: str = "#trading-alerts"
    sms_enabled: bool = False
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    twilio_to_number: str = ""
    sms_channels: list[str] = ["alerts:risk_breach", "alerts:circuit_breaker",
                                "alerts:system_error"]
    sms_cooldown_seconds: int = 300

class AutoExecuteConfig(BaseModel):
    """Auto-execute configuration with paper/live separation."""
    paper: AutoExecuteThresholds = Field(default_factory=AutoExecuteThresholds)
    live: AutoExecuteThresholds = Field(default_factory=AutoExecuteThresholds)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Slack RTM API | Socket Mode + Events API | 2020-2021 | RTM deprecated; Socket Mode is the replacement for behind-firewall apps |
| Slack message attachments | Block Kit | 2019-2020 | Block Kit is the standard for rich interactive messages; attachments are legacy |
| Custom webhook handling for interactive messages | slack-bolt framework | 2020+ | Bolt abstracts payload verification, ack deadlines, rate limiting |
| twilio-python-async (third-party) | twilio SDK native async (create_async) | 2023+ | Official async support via AsyncTwilioHttpClient; third-party package deprecated |
| HTTP Request URL for Slack interactivity | Socket Mode (no public endpoint) | 2020+ | Socket Mode eliminates ngrok/public URL requirement for development and on-prem |
| Classic Slack apps | Slack apps (new platform) | Ongoing, deadline Nov 2026 | Classic apps being discontinued; must use new app platform |

**Deprecated/outdated:**
- **Slack RTM API**: Replaced by Events API + Socket Mode. Do not use.
- **Slack message attachments**: Legacy. Use Block Kit blocks instead.
- **Classic Slack apps**: Being discontinued November 2026. Create a new Slack app, not a classic app.
- **twilio-python-async (third-party)**: Deprecated. Use official twilio SDK async or httpx directly.

## Integration Points with Existing Codebase

### Pipeline Modification (pipeline.py)
The existing `route_after_risk` function currently routes approved trades directly to the executor or END. Phase 8 modifies this to add an approval gate:
- Current: `risk_manager -> [conditional] -> executor | END`
- New: `risk_manager -> [conditional] -> approval_gate | executor | END`
- The approval_gate node is a new LangGraph node that calls `ApprovalManager.request_approval()`

### Event Publishing Points
New Redis pub/sub events should be published from:
1. **Executor node** (`_executor_node` in pipeline.py): After `submit_trade` returns, publish `alerts:trade_executed` or `alerts:trade_rejected`
2. **Circuit breaker** (`_activate_halt` in circuit_breaker.py): Publish `alerts:circuit_breaker` when halt activates
3. **Risk node** (`_risk_node` in pipeline.py): Publish `alerts:risk_breach` when proposals are rejected for risk violations
4. **App startup/shutdown** (`startup`/`shutdown` in app.py): Publish `alerts:system_error` on unexpected errors

### Config Extension (config.py)
Add `alerts: AlertConfig` and `auto_execute: AutoExecuteConfig` sections to the Settings class, following the existing pattern of nested Pydantic models loaded from YAML.

### Dashboard Extension (server.py)
Add a new `/api/approvals` REST router for:
- `GET /api/approvals/pending`: List pending approvals from Redis
- `POST /api/approvals/{id}/resolve`: Approve or reject from dashboard
- WebSocket channel `approvals` for real-time updates

### TradingApp Extension (app.py)
New components in `startup()`:
- `AlertRouter` (background task consuming Redis events)
- `SlackNotifier` (sends webhook messages)
- `SMSNotifier` (sends Twilio SMS)
- `ApprovalManager` (manages pending approvals)
- `AsyncSocketModeHandler` (background task for Slack interactive buttons)

New components in `connect_ib()`:
- Start AlertRouter background task
- Start Socket Mode handler background task (non-critical)

### Slack App Setup Requirements
Creating the Slack app requires manual steps outside of code:
1. Create a new Slack App at https://api.slack.com/apps
2. Enable Socket Mode (Settings > Socket Mode)
3. Generate App-Level Token with `connections:write` scope
4. Add Bot Token Scopes: `chat:write`, `commands` (for slash commands if desired)
5. Enable Interactivity (no Request URL needed with Socket Mode)
6. Install to workspace, get Bot Token (xoxb-*)
7. Store tokens in environment variables or config

## Open Questions

Things that couldn't be fully resolved:

1. **Pipeline blocking vs. decoupled approval**
   - What we know: The approval gate must not block subsequent pipeline runs. Two approaches: (a) the approval node returns immediately with "pending" status and a separate task handles resolution, or (b) the pipeline is split into pre-approval and post-approval subgraphs.
   - What's unclear: Which approach integrates more cleanly with LangGraph's StateGraph model. LangGraph nodes are expected to return state updates synchronously (within the graph execution).
   - Recommendation: Use approach (a) -- the approval node returns a "pending_approval" status in PipelineState and spawns a background task. The background task, on resolution, either invokes the executor directly (bypassing the graph) or stores the decision for the next pipeline run to pick up. This avoids fighting LangGraph's execution model.

2. **Approval persistence across process restarts**
   - What we know: Redis stores approval state. asyncio.Future objects are in-memory only. If the process restarts, in-memory futures are lost.
   - What's unclear: Whether to re-create futures from Redis on startup or simply auto-reject all pending approvals.
   - Recommendation: On startup, scan Redis for pending approvals. If any exist and their timeout hasn't expired, re-create futures and resume waiting. If timeout has expired, auto-reject (safe default). This provides crash recovery without complexity.

3. **Dashboard WebSocket channel for approvals**
   - What we know: The existing RedisBridge pattern maps Redis pub/sub channels to WebSocket topics. Adding an "approvals" channel is straightforward.
   - What's unclear: Whether the approval resolution should update the Slack message AND the dashboard simultaneously, or if they should be decoupled.
   - Recommendation: ApprovalManager.resolve() updates Redis and publishes to the alerts channel. Both the Slack handler and the dashboard bridge consume this event independently. This is the existing pub/sub fan-out pattern.

## Sources

### Primary (HIGH confidence)
- Existing codebase: `pipeline.py`, `executor_agent.py`, `circuit_breaker.py`, `publisher.py`, `bridge.py`, `config.py` -- verified patterns for Redis pub/sub, pipeline routing, config structure
- [Slack Bolt Python docs](https://docs.slack.dev/tools/bolt-python/concepts/actions/) -- action handling, ack() pattern
- [Slack Socket Mode docs](https://docs.slack.dev/apis/events-api/comparing-http-socket-mode/) -- HTTP vs Socket Mode comparison, connection limits
- [Slack Block Kit docs](https://docs.slack.dev/block-kit/) -- interactive message structure
- [slack-sdk PyPI](https://pypi.org/project/slack-sdk/) -- v3.41.0, March 2026
- [slack-bolt PyPI](https://pypi.org/project/slack-bolt/) -- v1.27.0, November 2025
- [Python asyncio docs](https://docs.python.org/3/library/asyncio-task.html) -- wait_for(), timeout patterns

### Secondary (MEDIUM confidence)
- [Twilio SMS quickstart](https://www.twilio.com/docs/messaging/quickstart) -- REST API structure for SMS
- [Twilio async blog](https://www.twilio.com/en-us/blog/twilio-python-helper-library-async) -- AsyncTwilioHttpClient, create_async pattern
- [httpx docs](https://www.python-httpx.org/) -- v0.28.1, async client API
- [Slack token types](https://docs.slack.dev/authentication/tokens/) -- app-level vs bot tokens

### Tertiary (LOW confidence)
- None -- all claims verified with official documentation or codebase inspection

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- slack-bolt and slack-sdk are the official Slack libraries; httpx is well-established; patterns verified against official docs
- Architecture: HIGH -- follows established project patterns (Redis pub/sub, pipeline routing, config structure, app lifecycle); LangGraph integration point is the only area with design ambiguity
- Pitfalls: HIGH -- sourced from official Slack docs (3-second ack deadline, Socket Mode connection limits) and observed codebase patterns (Redis state, config separation)

**Research date:** 2026-04-05
**Valid until:** 2026-05-05 (stable domain; Slack/Twilio APIs are mature)
