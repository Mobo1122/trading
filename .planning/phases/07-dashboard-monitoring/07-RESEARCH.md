# Phase 7: Dashboard & Monitoring - Research

**Researched:** 2026-04-04
**Domain:** Real-time web dashboard (FastAPI WebSocket backend + Next.js frontend)
**Confidence:** HIGH

## Summary

This phase introduces two new technology stacks to the project: a FastAPI WebSocket server as the real-time data bridge between the existing Redis pub/sub infrastructure and browser clients, and a Next.js frontend dashboard for visualizing positions, P&L, Greeks, trade history, agent reasoning, and system health.

The architecture is a clean three-tier pattern: the existing trading system writes to Redis channels (already implemented in Phase 2's dual-write pattern), a new FastAPI server subscribes to those Redis channels and bridges data to browser clients via WebSocket, and the Next.js dashboard consumes the WebSocket stream and renders the UI. For historical/on-demand data (trade history, agent reasoning chains, scenario analysis), the FastAPI server queries PostgreSQL/TimescaleDB directly via the existing SQLAlchemy async session factory.

The scenario analysis engine (DASH-06) is a pure Python computation that re-prices option positions under hypothetical changes to underlying price, IV, and time-to-expiration using Black-Scholes. This can be implemented with scipy.stats.norm (already available transitively) or the lightweight py_vollib library, avoiding the need for heavy dependencies.

**Primary recommendation:** Use FastAPI 0.135+ with native WebSocket support as the backend API server, bridge Redis pub/sub channels to WebSocket clients via an async channel-subscription manager, and build the dashboard with Next.js 15+ (App Router), shadcn/ui components, Recharts for charts, and Zustand for WebSocket state management.

## Standard Stack

The established libraries/tools for this domain:

### Core (Backend - Python)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastapi | >=0.135.0 | ASGI web framework with native WebSocket support | Industry standard for async Python APIs; native WebSocket handling without plugins |
| uvicorn[standard] | >=0.43.0 | ASGI server for running FastAPI | Default FastAPI deployment server; supports HTTP/1.1 and WebSocket |
| websockets | >=14.0 | WebSocket protocol library (FastAPI dependency) | Required by FastAPI for WebSocket support |

### Core (Frontend - TypeScript/React)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| next | >=15.2 | React framework with App Router | Full-stack React framework; SSR, routing, and build tooling in one |
| react / react-dom | >=19.0 | UI rendering | Required by Next.js |
| zustand | >=5.0 | Global state management for WebSocket data | Minimal boilerplate; supports state access outside React components (WebSocket handlers); per-component subscriptions optimal for high-frequency updates |
| recharts | >=3.8 | Charting library for P&L, Greeks visualization | React-first composable charts; used by shadcn/ui chart components |
| shadcn/ui | latest | UI component library (copy-paste, not npm) | Tailwind-based; includes pre-built chart components wrapping Recharts; no lock-in |
| tailwindcss | >=4.0 | Utility CSS framework | Required by shadcn/ui; standard in Next.js ecosystem |

### Supporting (Backend)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| scipy | >=1.12 | Black-Scholes pricing (norm.cdf) for scenario analysis | Scenario analysis endpoint; already a transitive dependency |
| numpy | >=1.26 | Array math for batch scenario calculations | Vectorized pricing across multiple scenarios |

### Supporting (Frontend)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| lucide-react | latest | Icons | Used by shadcn/ui components |
| clsx + tailwind-merge | latest | Conditional CSS classes | shadcn/ui utility requirement |
| date-fns | latest | Date formatting for timestamps | Trade history, timestamps display |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Zustand | Redux Toolkit | Redux adds boilerplate; Zustand is simpler for WebSocket state |
| Recharts | Tremor | Tremor is higher-level but adds another component library layer |
| WebSocket | Server-Sent Events (SSE) | SSE is simpler for one-way streaming but dashboard needs bidirectional (scenario analysis requests) |
| scipy Black-Scholes | py_vollib | py_vollib is faster but adds dependency; scipy is already available transitively |
| Next.js | Vite + React Router | Next.js provides SSR, routing, and build tooling; Vite requires more manual setup |

**Installation (Backend):**
```bash
# Add to pyproject.toml dependencies
uv add "fastapi[standard]>=0.135.0" "uvicorn[standard]>=0.43.0" scipy numpy
```

**Installation (Frontend):**
```bash
# Create Next.js app in project root
npx create-next-app@latest dashboard --typescript --tailwind --eslint --app --src-dir
cd dashboard
pnpm dlx shadcn@latest init
pnpm dlx shadcn@latest add card table badge button tabs separator chart
pnpm add zustand recharts date-fns
```

## Architecture Patterns

### Recommended Project Structure
```
src/trading/
  dashboard/                  # New: FastAPI dashboard server
    __init__.py
    server.py                 # FastAPI app factory, lifespan, CORS
    ws/
      __init__.py
      manager.py              # WebSocket connection manager with channel subscriptions
      bridge.py               # Redis pub/sub -> WebSocket bridge
    routes/
      __init__.py
      positions.py            # REST: positions, P&L endpoints
      trades.py               # REST: trade history with reasoning
      health.py               # REST + WS: system health
      scenarios.py            # REST: scenario analysis engine
    models.py                 # Pydantic response models for API
    scenario_engine.py        # Black-Scholes pricing engine

dashboard/                    # New: Next.js frontend (project root level)
  src/
    app/
      layout.tsx              # Root layout with providers
      page.tsx                # Dashboard home (redirect to positions)
      positions/
        page.tsx              # Positions + P&L view
      greeks/
        page.tsx              # Portfolio Greeks view
      trades/
        page.tsx              # Trade history + reasoning chains
      health/
        page.tsx              # System health monitoring
      scenarios/
        page.tsx              # P&L scenario analysis
    components/
      ui/                     # shadcn/ui components (auto-generated)
      positions/
        positions-table.tsx   # Position table with real-time P&L
        portfolio-summary.tsx # Portfolio-level P&L summary
      greeks/
        greeks-display.tsx    # Portfolio Greeks cards
        greeks-chart.tsx      # Greeks over time chart
      trades/
        trade-history.tsx     # Trade history table
        reasoning-chain.tsx   # Agent reasoning display
      health/
        health-panel.tsx      # Connection status, heartbeats
        data-freshness.tsx    # Data stream freshness indicators
      scenarios/
        scenario-form.tsx     # What-if parameter inputs
        scenario-results.tsx  # Scenario P&L display
    hooks/
      use-websocket.ts        # WebSocket connection hook
    stores/
      positions-store.ts      # Zustand store for position data
      greeks-store.ts         # Zustand store for Greeks data
      health-store.ts         # Zustand store for health status
    lib/
      ws-client.ts            # WebSocket client with reconnection
      api.ts                  # REST API client helpers
    types/
      index.ts                # Shared TypeScript types matching Pydantic models
```

### Pattern 1: Redis-to-WebSocket Bridge
**What:** A background task subscribes to Redis pub/sub channels and fans out messages to WebSocket clients that have subscribed to corresponding topics.
**When to use:** Always -- this is the core data flow pattern for the dashboard.
**Example:**
```python
# Source: FastAPI docs + Redis pub/sub bridge pattern
import asyncio
import json
from collections import defaultdict
from fastapi import WebSocket, WebSocketDisconnect

class ChannelManager:
    """Manages WebSocket subscriptions to Redis-backed channels."""

    def __init__(self):
        # channel_name -> set of WebSocket connections
        self._subscriptions: dict[str, set[WebSocket]] = defaultdict(set)
        self._ws_channels: dict[WebSocket, set[str]] = defaultdict(set)

    async def subscribe(self, ws: WebSocket, channel: str):
        self._subscriptions[channel].add(ws)
        self._ws_channels[ws].add(channel)

    async def unsubscribe_all(self, ws: WebSocket):
        for channel in self._ws_channels.pop(ws, set()):
            self._subscriptions[channel].discard(ws)
            if not self._subscriptions[channel]:
                del self._subscriptions[channel]

    async def broadcast(self, channel: str, message: str):
        dead = []
        for ws in self._subscriptions.get(channel, set()):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.unsubscribe_all(ws)
```

### Pattern 2: Zustand Store with WebSocket Integration
**What:** Zustand stores that receive updates from WebSocket messages outside React component context.
**When to use:** All real-time data (positions, Greeks, health).
**Example:**
```typescript
// Source: Zustand docs + WebSocket pattern
import { create } from 'zustand'

interface Position {
  symbol: string
  quantity: number
  avgCost: number
  currentPrice: number
  pnl: number
  pnlPercent: number
}

interface PositionsState {
  positions: Record<string, Position>
  portfolioPnl: number
  updatePosition: (pos: Position) => void
  setPositions: (positions: Position[]) => void
}

export const usePositionsStore = create<PositionsState>((set) => ({
  positions: {},
  portfolioPnl: 0,
  updatePosition: (pos) =>
    set((state) => {
      const updated = { ...state.positions, [pos.symbol]: pos }
      const portfolioPnl = Object.values(updated).reduce((sum, p) => sum + p.pnl, 0)
      return { positions: updated, portfolioPnl }
    }),
  setPositions: (positions) =>
    set(() => {
      const map = Object.fromEntries(positions.map((p) => [p.symbol, p]))
      const portfolioPnl = positions.reduce((sum, p) => sum + p.pnl, 0)
      return { positions: map, portfolioPnl }
    }),
}))

// Can be called from WebSocket handler outside React:
// usePositionsStore.getState().updatePosition(data)
```

### Pattern 3: FastAPI Lifespan for Redis Subscriber Tasks
**What:** Use FastAPI's lifespan context manager to start/stop the Redis subscriber background task that feeds the WebSocket bridge.
**When to use:** Application startup/shutdown lifecycle.
**Example:**
```python
# Source: FastAPI lifespan docs
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: connect to Redis and start subscriber tasks
    redis = await create_redis_connection()
    bridge = RedisBridge(redis, channel_manager)
    task = asyncio.create_task(bridge.listen())

    yield  # App is running

    # Shutdown: cancel subscriber and close Redis
    task.cancel()
    await redis.aclose()

app = FastAPI(lifespan=lifespan)
```

### Pattern 4: Scenario Analysis Engine (Pure Python)
**What:** Black-Scholes repricing of option positions under hypothetical parameter changes.
**When to use:** DASH-06 scenario analysis.
**Example:**
```python
# Source: Black-Scholes analytical formula with scipy
import numpy as np
from scipy.stats import norm

def black_scholes_price(
    S: float,       # Underlying price
    K: float,       # Strike price
    T: float,       # Time to expiration (years)
    r: float,       # Risk-free rate
    sigma: float,   # Implied volatility
    option_type: str # "C" or "P"
) -> float:
    """Price a European option using Black-Scholes."""
    if T <= 0:
        # At expiration, intrinsic value
        if option_type == "C":
            return max(S - K, 0)
        return max(K - S, 0)

    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    if option_type == "C":
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

def scenario_pnl(
    positions: list[dict],
    underlying_change_pct: float,  # e.g., +5.0 for +5%
    iv_change_pct: float,          # e.g., -10.0 for -10% relative
    days_forward: int,             # e.g., 7 for T+7
    risk_free_rate: float = 0.05,
) -> dict:
    """Calculate portfolio P&L under scenario."""
    total_current = 0.0
    total_scenario = 0.0

    for pos in positions:
        S = pos["underlying_price"]
        K = pos["strike"]
        T = pos["dte"] / 365.0
        sigma = pos["implied_vol"]
        qty = pos["quantity"]
        multiplier = pos.get("multiplier", 100)
        opt_type = pos["right"]  # "C" or "P"

        # Current theoretical value
        current_price = black_scholes_price(S, K, T, risk_free_rate, sigma, opt_type)

        # Scenario values
        S_new = S * (1 + underlying_change_pct / 100)
        sigma_new = sigma * (1 + iv_change_pct / 100)
        T_new = max((pos["dte"] - days_forward) / 365.0, 0)

        scenario_price = black_scholes_price(S_new, K, T_new, risk_free_rate, sigma_new, opt_type)

        total_current += current_price * qty * multiplier
        total_scenario += scenario_price * qty * multiplier

    return {
        "current_value": round(total_current, 2),
        "scenario_value": round(total_scenario, 2),
        "pnl": round(total_scenario - total_current, 2),
        "pnl_percent": round(
            ((total_scenario - total_current) / abs(total_current) * 100)
            if total_current != 0 else 0, 2
        ),
    }
```

### Anti-Patterns to Avoid
- **Polling REST endpoints for real-time data:** Use WebSocket for streaming data; REST only for on-demand queries (trade history, scenario analysis).
- **Shared mutable state between FastAPI workers:** Use Redis as the single source of truth; the connection manager is per-process. For this single-instance trading system, one uvicorn worker is sufficient.
- **Fetching entire trade history on every page load:** Paginate trade history queries; use cursor-based pagination for the trade history endpoint.
- **Putting WebSocket logic in Next.js API routes:** Next.js API routes are serverless-oriented; use the Python FastAPI server for all WebSocket handling.
- **Blocking the asyncio event loop in WebSocket handlers:** All DB queries must use async SQLAlchemy; all Redis operations must be async.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| WebSocket reconnection (client) | Custom reconnection logic | Reconnecting WebSocket wrapper with exponential backoff | Edge cases: offline detection, tab visibility, duplicate connections |
| Option pricing for scenarios | Custom BS implementation | scipy.stats.norm-based Black-Scholes (see code example above) | Numerical stability at extreme strikes/expirations |
| UI component design | Custom styled components | shadcn/ui pre-built components (table, card, badge, tabs) | Consistent design, dark mode, accessibility built in |
| Chart rendering | Custom SVG/Canvas charts | Recharts via shadcn/ui chart components | Responsive, themed, composable React chart components |
| JSON serialization for WebSocket | Custom serializers | Pydantic model_dump_json() on backend, native JSON.parse on frontend | Already used throughout the project; type-safe serialization |
| Date/time formatting | Custom date formatters | date-fns (formatDistanceToNow, format) | Locale-aware, tree-shakeable, handles timezone edge cases |
| CSS utilities | Custom CSS classes | Tailwind CSS utility classes | Already required by shadcn/ui; consistent with component library |

**Key insight:** The dashboard is primarily a data display layer. The trading system already computes and stores all the data (positions, Greeks, P&L, agent reasoning, health status). The dashboard layer should be thin: receive data, format it, display it. Do not re-implement business logic in the frontend.

## Common Pitfalls

### Pitfall 1: Blocking the Event Loop in WebSocket Handlers
**What goes wrong:** Synchronous database queries or CPU-bound calculations in async WebSocket handlers block all concurrent WebSocket connections on that worker.
**Why it happens:** Mixing sync and async code; forgetting that Black-Scholes calculations with many positions can be CPU-intensive.
**How to avoid:** Use async SQLAlchemy for all DB queries. For CPU-bound scenario analysis with many positions, use `asyncio.to_thread()` or `loop.run_in_executor()`.
**Warning signs:** Dashboard freezes or delays affecting all clients simultaneously.

### Pitfall 2: WebSocket Connection Leaks
**What goes wrong:** Dead WebSocket connections accumulate in the connection manager, causing broadcast failures and memory growth.
**Why it happens:** Mobile/flaky networks disconnect without sending a close frame; client tabs left open during sleep.
**How to avoid:** Implement heartbeat/ping-pong at the application level (send ping every 30s, disconnect if no pong within 10s). Wrap all send operations in try/except and clean up dead connections.
**Warning signs:** Growing memory usage on the FastAPI server; increasing broadcast latency.

### Pitfall 3: Next.js App Router Activity/Keep-Alive Behavior
**What goes wrong:** When navigating between pages, Next.js App Router wraps the previous page with `display: none` rather than unmounting it. WebSocket listeners and intervals from the previous page continue running.
**Why it happens:** Next.js optimizes page transitions by keeping previous pages in the DOM.
**How to avoid:** Use `useEffect` cleanup functions properly. Consider a single WebSocket connection at the layout level (not per-page), with Zustand stores receiving all updates. Pages subscribe to the store data they need.
**Warning signs:** Duplicate WebSocket connections; state updates triggering re-renders on hidden pages.

### Pitfall 4: WebSocket Authentication
**What goes wrong:** Browsers cannot set custom headers on WebSocket connections, so Bearer token auth patterns from REST APIs don't work.
**Why it happens:** WebSocket protocol limitation in browsers.
**How to avoid:** Use query parameter tokens (`ws://host/ws?token=xyz`) with short-lived tokens (60s lifetime for connection handshake). For this internal trading dashboard, cookie-based auth or even a simple shared token is acceptable.
**Warning signs:** Authentication failures on WebSocket connect.

### Pitfall 5: Stale Data on Initial Page Load
**What goes wrong:** WebSocket only delivers changes. When a client first connects, they see an empty dashboard until the next update arrives.
**Why it happens:** Pub/sub is ephemeral -- clients miss messages sent before they subscribed.
**How to avoid:** On WebSocket connect, immediately send a snapshot of current state from Redis HSET caches (already populated by Phase 2's dual-write pattern). The HSET latest-value cache (`mktdata:latest:quote:{symbol}`, `mktdata:latest:greeks:{con_id}`) was designed for exactly this use case.
**Warning signs:** Dashboard shows blanks until first market data tick.

### Pitfall 6: Over-rendering from High-Frequency Updates
**What goes wrong:** Market data updates every 250ms per symbol cause excessive React re-renders, degrading UI performance.
**Why it happens:** Naively pushing every Redis pub/sub message to every WebSocket client and re-rendering the entire position table.
**How to avoid:** Throttle updates on the server side (batch updates every 500ms-1s for display). Use Zustand's per-field subscriptions so only changed positions trigger re-renders. Use `React.memo` on table rows.
**Warning signs:** High CPU usage in browser; janky scrolling; React DevTools showing excessive renders.

### Pitfall 7: Scenario Engine Returning Stale Greeks
**What goes wrong:** Scenario analysis uses stale position data from the database instead of the latest real-time data.
**Why it happens:** Querying PostgreSQL for position data when Redis has fresher data.
**How to avoid:** For scenario analysis, fetch current positions from the database (authoritative for positions held) but overlay real-time Greeks/prices from Redis HSET caches.
**Warning signs:** Scenario results don't match what the position display shows.

## Code Examples

Verified patterns from official sources:

### FastAPI WebSocket Endpoint with Channel Subscription
```python
# Source: FastAPI WebSocket docs + Redis bridge pattern
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import json

app = FastAPI()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    channel_mgr = app.state.channel_manager

    try:
        # Send initial snapshot on connect
        snapshot = await get_current_snapshot()
        await websocket.send_json({"type": "snapshot", "data": snapshot})

        while True:
            # Receive subscription requests from client
            message = await websocket.receive_json()
            msg_type = message.get("type")

            if msg_type == "subscribe":
                channel = message["channel"]
                await channel_mgr.subscribe(websocket, channel)
                # Send channel-specific snapshot
                data = await get_channel_snapshot(channel)
                await websocket.send_json({
                    "type": "channel_snapshot",
                    "channel": channel,
                    "data": data,
                })
            elif msg_type == "unsubscribe":
                channel = message["channel"]
                await channel_mgr.unsubscribe(websocket, channel)
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        await channel_mgr.unsubscribe_all(websocket)
```

### Redis Subscriber Background Task
```python
# Source: redis.asyncio pub/sub docs + FastAPI lifespan pattern
import asyncio
import json
from redis.asyncio import Redis

class RedisBridge:
    """Bridges Redis pub/sub channels to WebSocket clients."""

    # Channels the dashboard cares about
    CHANNELS = [
        "mktdata:quote:*",      # All quote updates
        "mktdata:greeks:*",     # All Greeks updates
        "mktdata:stale",        # Staleness alerts
        "dashboard:positions",  # Position updates
        "dashboard:health",     # Health status updates
    ]

    def __init__(self, redis: Redis, channel_manager):
        self._redis = redis
        self._channel_manager = channel_manager

    async def listen(self):
        """Subscribe to Redis channels and forward to WebSocket clients."""
        pubsub = self._redis.pubsub()
        await pubsub.psubscribe(*self.CHANNELS)

        try:
            async for message in pubsub.listen():
                if message["type"] not in ("pmessage", "message"):
                    continue
                channel = message.get("channel", "")
                data = message.get("data", "")
                # Map Redis channel to dashboard topic
                topic = self._map_channel(channel)
                if topic:
                    payload = json.dumps({
                        "type": "update",
                        "channel": topic,
                        "data": json.loads(data) if isinstance(data, str) else data,
                    })
                    await self._channel_manager.broadcast(topic, payload)
        except asyncio.CancelledError:
            await pubsub.punsubscribe()
            await pubsub.aclose()

    def _map_channel(self, redis_channel: str) -> str | None:
        """Map Redis channel names to dashboard topic names."""
        if redis_channel.startswith("mktdata:quote:"):
            symbol = redis_channel.split(":")[-1]
            return f"quotes:{symbol}"
        if redis_channel.startswith("mktdata:greeks:"):
            parts = redis_channel.split(":")
            return f"greeks:{parts[-2]}:{parts[-1]}"
        if redis_channel == "mktdata:stale":
            return "staleness"
        if redis_channel == "dashboard:positions":
            return "positions"
        if redis_channel == "dashboard:health":
            return "health"
        return None
```

### WebSocket Client Hook (Next.js)
```typescript
// Source: Standard React WebSocket pattern with Zustand
"use client"

import { useEffect, useRef, useCallback } from "react"
import { usePositionsStore } from "@/stores/positions-store"
import { useHealthStore } from "@/stores/health-store"

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/ws"
const RECONNECT_DELAY = 3000
const PING_INTERVAL = 30000

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<NodeJS.Timeout>()
  const pingTimer = useRef<NodeJS.Timeout>()

  const connect = useCallback(() => {
    const ws = new WebSocket(WS_URL)
    wsRef.current = ws

    ws.onopen = () => {
      // Subscribe to channels
      ws.send(JSON.stringify({ type: "subscribe", channel: "positions" }))
      ws.send(JSON.stringify({ type: "subscribe", channel: "health" }))

      // Start heartbeat
      pingTimer.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "ping" }))
        }
      }, PING_INTERVAL)
    }

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data)
      // Route to appropriate Zustand store
      switch (msg.type) {
        case "snapshot":
        case "channel_snapshot":
          handleSnapshot(msg)
          break
        case "update":
          handleUpdate(msg)
          break
      }
    }

    ws.onclose = () => {
      clearInterval(pingTimer.current)
      reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY)
    }

    ws.onerror = () => ws.close()
  }, [])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectTimer.current)
      clearInterval(pingTimer.current)
      wsRef.current?.close()
    }
  }, [connect])

  return wsRef
}

function handleSnapshot(msg: any) {
  if (msg.channel === "positions") {
    usePositionsStore.getState().setPositions(msg.data)
  }
}

function handleUpdate(msg: any) {
  if (msg.channel === "positions") {
    usePositionsStore.getState().updatePosition(msg.data)
  } else if (msg.channel === "health") {
    useHealthStore.getState().setHealth(msg.data)
  }
}
```

### FastAPI REST Endpoint for Trade History with Reasoning
```python
# Source: SQLAlchemy async query pattern (existing project style)
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/trades", tags=["trades"])

@router.get("/history")
async def get_trade_history(
    session: AsyncSession = Depends(get_db_session),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Fetch trade history with agent reasoning chains."""
    # Orders with their execution records
    stmt = (
        select(Order)
        .where(Order.current_state == "FILLED")
        .order_by(desc(Order.updated_at))
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    orders = result.scalars().all()

    # For each order, fetch the agent decision log by proposal_id
    trade_history = []
    for order in orders:
        reasoning = None
        if order.proposal_id:
            reasoning_stmt = (
                select(AgentDecisionLog)
                .where(AgentDecisionLog.run_id == order.proposal_id)
                .order_by(AgentDecisionLog.stage_order)
            )
            reasoning_result = await session.execute(reasoning_stmt)
            reasoning = [
                {
                    "agent": r.agent_name,
                    "reasoning": r.reasoning,
                    "output_summary": r.output_summary,
                    "duration_ms": r.duration_ms,
                }
                for r in reasoning_result.scalars().all()
            ]

        trade_history.append({
            "order_id": order.id,
            "symbol": order.symbol,
            "action": order.action,
            "quantity": order.quantity,
            "fill_price": order.fill_price,
            "commission": order.total_commission,
            "created_at": order.created_at.isoformat(),
            "updated_at": order.updated_at.isoformat(),
            "reasoning_chain": reasoning,
        })

    return {"trades": trade_history, "total": len(trade_history)}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Socket.IO (Python + JS) | Native WebSocket via FastAPI + browser API | 2024+ | No extra dependency; FastAPI handles WS natively |
| Redux for state | Zustand for global state | 2023+ | 70% less boilerplate; better WebSocket integration |
| Create React App | Next.js App Router | 2023+ | SSR, file-based routing, server components |
| Custom CSS | Tailwind + shadcn/ui | 2023+ | Faster development; consistent design system |
| Polling for real-time data | WebSocket with Redis bridge | Always preferred | Sub-second latency vs seconds with polling |
| Pages Router (Next.js) | App Router (Next.js 13+) | 2023 | Server components, layouts, loading states |
| Recharts alone | shadcn/ui chart components (wrapping Recharts) | 2024 | Pre-styled, themed, copy-paste ready |

**Deprecated/outdated:**
- `aioredis` library: Merged into `redis-py` as `redis.asyncio` (already used in this project)
- `Socket.IO` for Python: Unnecessary complexity when FastAPI has native WebSocket support
- `Next.js Pages Router`: Still works but App Router is the recommended default
- `Redux`: Still maintained but Zustand is preferred for new projects, especially with WebSocket patterns

## Open Questions

Things that couldn't be fully resolved:

1. **Position data source for real-time P&L**
   - What we know: IB provides portfolio positions via `ib.positions()` and `ib.portfolio()`. The system has order records in PostgreSQL but may not have a dedicated positions table with real-time mark-to-market.
   - What's unclear: Whether a new `positions` table is needed, or if we can derive positions from filled orders + IB portfolio data at dashboard server startup.
   - Recommendation: During plan 07-01, define a mechanism to periodically sync IB portfolio data to Redis (e.g., a new `dashboard:positions` channel) so the dashboard has a consistent position source. The FastAPI server should query IB positions on startup, cache in Redis, and update via periodic polling (every 5-10s).

2. **Dashboard deployment model**
   - What we know: The trading system runs as a single Python process. The dashboard server could run in the same process or as a separate service.
   - What's unclear: Whether FastAPI should be embedded in TradingApp or run as a separate process.
   - Recommendation: Run FastAPI as a **separate process** that connects to the same Redis and PostgreSQL. This keeps the trading engine isolated from dashboard concerns, and a dashboard crash cannot affect trading. Use docker-compose to add the dashboard service.

3. **Frontend deployment**
   - What we know: Next.js requires Node.js runtime. The project currently has no Node.js infrastructure.
   - What's unclear: Whether to use `next start` (Node.js server), `next export` (static), or containerize.
   - Recommendation: Use `next dev` during development, `next build && next start` for production, add a `dashboard-ui` service to docker-compose. Static export won't work because we need client-side WebSocket connections (but no server-side rendering is strictly required -- could also use Vite, but Next.js provides better DX).

4. **Linking orders to pipeline run_ids for reasoning chains**
   - What we know: `AgentDecisionLog` has `run_id`, `Order` has `proposal_id`. These need to be the same value for the reasoning chain join to work.
   - What's unclear: Whether `proposal_id` on orders is consistently set to the pipeline `run_id` in the current implementation.
   - Recommendation: Verify during planning that the executor agent sets `proposal_id` to the `run_id` when creating orders. If not, add this linkage.

## Sources

### Primary (HIGH confidence)
- [FastAPI WebSocket docs](https://fastapi.tiangolo.com/advanced/websockets/) - WebSocket endpoint API, ConnectionManager pattern, dependency injection
- [FastAPI PyPI](https://pypi.org/project/fastapi/) - Version 0.135.3, Python >=3.10
- [shadcn/ui installation](https://ui.shadcn.com/docs/installation/next) - Next.js setup steps
- [Zustand npm](https://www.npmjs.com/package/zustand) - Version 5.0.12
- [Recharts npm](https://www.npmjs.com/package/recharts) - Version 3.8.1

### Secondary (MEDIUM confidence)
- [Redis PubSub + FastAPI WebSocket scaling](https://medium.com/@nandagopal05/scaling-websockets-with-pub-sub-using-python-redis-fastapi-b16392ffe291) - Verified architecture pattern with code
- [FastAPI Redis WebSocket Gist](https://gist.github.com/timhughes/313c89a0d587a25506e204573c8017e4) - Bidirectional Redis PubSub bridge pattern
- [shadcn/ui charts](https://www.shadcn.io/charts) - 53 pre-built chart components wrapping Recharts
- [React state management 2026](https://dev.to/bean_bean/the-ultimate-guide-to-react-state-management-2026-28bh) - Zustand recommended for global state with WebSocket

### Tertiary (LOW confidence)
- Next.js 16.2 is latest but 15.x is stable and well-documented; unclear whether to target 15 or 16 (recommend 15.x for stability)
- py_vollib performance claims (faster than scipy) -- unverified but not critical since scipy is sufficient

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries verified on PyPI/npm with current versions; FastAPI WebSocket API verified via official docs
- Architecture: HIGH - Redis-to-WebSocket bridge pattern is well-documented and directly maps to existing Redis pub/sub infrastructure (Phase 2)
- Pitfalls: HIGH - Common WebSocket pitfalls verified across multiple authoritative sources; App Router behavior verified via Next.js docs
- Scenario engine: MEDIUM - Black-Scholes implementation is standard but specific integration with existing position data needs validation during planning
- Frontend structure: MEDIUM - shadcn/ui + Zustand + Recharts is the current standard stack but specific component composition is based on common patterns, not a verified reference implementation

**Research date:** 2026-04-04
**Valid until:** 2026-05-04 (30 days -- stack is stable; no major releases expected)
