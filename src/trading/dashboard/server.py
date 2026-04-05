"""FastAPI dashboard server with WebSocket and REST endpoints.

Provides the dashboard app factory, WebSocket endpoint for real-time
streaming, health check endpoint, and database session dependency
for downstream route handlers.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from trading.cache.redis import close_redis_client, create_redis_client
from trading.config import Settings
from trading.dashboard.routes.greeks import router as greeks_router
from trading.dashboard.routes.health import router as health_router
from trading.dashboard.routes.positions import router as positions_router
from trading.dashboard.routes.trades import router as trades_router
from trading.dashboard.ws.bridge import RedisBridge
from trading.dashboard.ws.manager import ChannelManager
from trading.db.engine import create_db_engine, create_session_factory

logger = structlog.get_logger().bind(component="dashboard_server")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI dashboard application.

    Sets up CORS, lifespan events (Redis, DB, ChannelManager, RedisBridge),
    WebSocket endpoint, health check, and database session dependency.

    Args:
        settings: Application settings. Loads from defaults if None.

    Returns:
        Configured FastAPI application instance.
    """
    if settings is None:
        settings = Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Manage application lifecycle: startup and shutdown resources."""
        log = structlog.get_logger().bind(component="dashboard_server")

        # Startup: create Redis, DB, channel manager, and bridge
        redis_client = create_redis_client(settings.redis.url)
        db_engine = create_db_engine(
            settings.database.url,
            pool_size=settings.database.pool_size,
            pool_overflow=settings.database.pool_overflow,
        )
        session_factory = create_session_factory(db_engine)
        channel_manager = ChannelManager()
        bridge = RedisBridge(
            redis=redis_client,
            channel_manager=channel_manager,
            throttle_ms=settings.dashboard.update_throttle_ms,
        )
        bridge_task = asyncio.create_task(bridge.listen())

        # Store on app.state for access in endpoints
        app.state.redis = redis_client
        app.state.db_engine = db_engine
        app.state.session_factory = session_factory
        app.state.channel_manager = channel_manager
        app.state.bridge_task = bridge_task

        log.info(
            "dashboard.started",
            host=settings.dashboard.host,
            port=settings.dashboard.port,
        )

        yield

        # Shutdown: cancel bridge, close Redis, dispose DB
        bridge_task.cancel()
        try:
            await bridge_task
        except asyncio.CancelledError:
            pass

        try:
            await close_redis_client(redis_client)
        except Exception:
            log.warning("dashboard.redis_close_failed", exc_info=True)

        try:
            await db_engine.dispose()
        except Exception:
            log.warning("dashboard.db_dispose_failed", exc_info=True)

        log.info("dashboard.shutdown_complete")

    app = FastAPI(
        title="Trading Dashboard API",
        lifespan=lifespan,
    )

    # Configure CORS for Next.js dev server
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.dashboard.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include REST route modules
    app.include_router(greeks_router)
    app.include_router(health_router)
    app.include_router(positions_router)
    app.include_router(trades_router)

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        """WebSocket endpoint for real-time dashboard streaming.

        On connect, sends an initial snapshot. Then listens for
        subscribe/unsubscribe/ping messages from the client.
        """
        await ws.accept()
        channel_manager: ChannelManager = ws.app.state.channel_manager
        redis_client = ws.app.state.redis

        try:
            # Send initial snapshot (populated by later plans via Redis)
            await ws.send_json({"type": "snapshot", "data": {}})

            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await ws.send_json({"type": "error", "data": "invalid JSON"})
                    continue

                msg_type = msg.get("type")

                if msg_type == "subscribe":
                    channel = msg.get("channel")
                    if channel:
                        await channel_manager.subscribe(ws, channel)
                        # Send channel-specific snapshot from Redis if available
                        snapshot_data = await _get_channel_snapshot(
                            redis_client, channel
                        )
                        await ws.send_json({
                            "type": "snapshot",
                            "channel": channel,
                            "data": snapshot_data,
                        })

                elif msg_type == "unsubscribe":
                    channel = msg.get("channel")
                    if channel:
                        await channel_manager.unsubscribe(ws, channel)

                elif msg_type == "ping":
                    await ws.send_json({"type": "pong"})

        except WebSocketDisconnect:
            pass
        finally:
            await channel_manager.unsubscribe_all(ws)

    @app.get("/api/health")
    async def health_check():
        """Simple health check endpoint."""
        return {"status": "ok"}

    return app


async def _get_channel_snapshot(redis_client, channel: str) -> dict | list | None:
    """Retrieve a snapshot for a channel from Redis cache.

    Maps dashboard topic names to Redis keys for latest-value lookup.

    Args:
        redis_client: Async Redis client.
        channel: Dashboard topic name.

    Returns:
        Cached data or None if not available.
    """
    try:
        if channel.startswith("quotes:"):
            symbol = channel[len("quotes:"):]
            data = await redis_client.hgetall(f"mktdata:latest:quote:{symbol}")
            return data if data else None

        if channel.startswith("greeks:"):
            # greeks:{symbol}:{con_id} -> mktdata:latest:greeks:{con_id}
            parts = channel.split(":")
            if len(parts) >= 3:
                con_id = parts[-1]
                data = await redis_client.hgetall(
                    f"mktdata:latest:greeks:{con_id}"
                )
                return data if data else None

        if channel == "positions":
            data = await redis_client.get("dashboard:positions")
            if data:
                return json.loads(data)

        if channel == "health":
            # Aggregate health keys
            ib_status = await redis_client.get("dashboard:ib_status")
            heartbeat = await redis_client.get("dashboard:heartbeat")
            pipeline_status = await redis_client.get("dashboard:pipeline_status")
            return {
                "ib_status": ib_status,
                "heartbeat": heartbeat,
                "pipeline_status": pipeline_status,
            }

        if channel == "portfolio_greeks":
            data = await redis_client.get("dashboard:portfolio_greeks")
            if data:
                return json.loads(data)

    except Exception:
        logger.warning(
            "channel_snapshot.failed",
            channel=channel,
            exc_info=True,
        )

    return None


from trading.dashboard.deps import get_db_session  # noqa: E402 -- re-export

__all__ = ["create_app", "get_db_session", "run_server"]


def run_server(settings: Settings | None = None) -> None:
    """Run the dashboard server with uvicorn.

    Convenience function for starting the server from CLI or scripts.

    Args:
        settings: Application settings. Loads from defaults if None.
    """
    if settings is None:
        settings = Settings()
    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.dashboard.host,
        port=settings.dashboard.port,
    )
