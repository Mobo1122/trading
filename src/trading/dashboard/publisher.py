"""Dashboard publisher for writing TradingApp state to Redis.

Periodically publishes IB connection status, heartbeat, pipeline status,
current positions, and aggregated portfolio Greeks to Redis keys for the
dashboard server to consume. Uses both SET (for snapshots) and PUBLISH
(for real-time WebSocket streaming) to support pull and push access.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import structlog


class DashboardPublisher:
    """Background task that writes TradingApp state to Redis for the dashboard.

    Publishes to Redis keys:
      - dashboard:ib_status: "connected" or "disconnected"
      - dashboard:heartbeat: ISO timestamp of last publish
      - dashboard:pipeline_status: "idle", "running", or "error"
      - dashboard:positions: JSON array of current positions
      - dashboard:portfolio_greeks: JSON object with aggregated Greeks

    Also publishes to Redis pub/sub channels for real-time push:
      - dashboard:health: combined health blob
      - dashboard:positions: position update
      - dashboard:portfolio_greeks: aggregated Greeks update

    Args:
        redis_client: Async Redis client instance.
        ib: IB connection instance (ib_async IB object).
        health_monitor: Optional HealthMonitor for pipeline status.
        interval: Seconds between publish cycles (default 5).
    """

    def __init__(
        self,
        redis_client: Any,
        ib: Any,
        health_monitor: Any | None = None,
        interval: int = 5,
    ) -> None:
        self._redis = redis_client
        self._ib = ib
        self._health_monitor = health_monitor
        self._interval = interval
        self._task: asyncio.Task | None = None
        self._log = structlog.get_logger().bind(component="dashboard_publisher")

    async def start(self) -> None:
        """Start the background publish loop."""
        self._task = asyncio.create_task(self._publish_loop())
        self._log.info("dashboard_publisher.started", interval=self._interval)

    async def stop(self) -> None:
        """Stop the background publish loop."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            self._log.info("dashboard_publisher.stopped")

    async def _publish_loop(self) -> None:
        """Run the publish cycle every interval seconds.

        Each publish operation is independently try/excepted so a single
        failure does not stop the loop (non-fatal, matching project convention).
        """
        try:
            while True:
                await self._publish_ib_status()
                await self._publish_heartbeat()
                await self._publish_pipeline_status()
                await self._publish_positions()
                await self._publish_portfolio_greeks()

                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            raise

    async def _publish_ib_status(self) -> None:
        """Publish IB connection status to Redis."""
        try:
            connected = False
            try:
                connected = self._ib.isConnected()
            except Exception:
                pass

            status = "connected" if connected else "disconnected"
            await self._redis.set("dashboard:ib_status", status)

            health_blob = json.dumps({
                "ib_status": status,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            await self._redis.publish("dashboard:health", health_blob)
        except Exception:
            self._log.warning("dashboard_publisher.ib_status_failed", exc_info=True)

    async def _publish_heartbeat(self) -> None:
        """Publish heartbeat timestamp to Redis."""
        try:
            now = datetime.now(timezone.utc).isoformat()
            await self._redis.set("dashboard:heartbeat", now)
        except Exception:
            self._log.warning("dashboard_publisher.heartbeat_failed", exc_info=True)

    async def _publish_pipeline_status(self) -> None:
        """Publish pipeline status to Redis."""
        try:
            status = "idle"
            if self._health_monitor is not None:
                try:
                    health = self._health_monitor.current_health
                    if hasattr(health, "value"):
                        status = health.value
                    elif isinstance(health, str):
                        status = health
                except Exception:
                    pass

            await self._redis.set("dashboard:pipeline_status", status)
        except Exception:
            self._log.warning(
                "dashboard_publisher.pipeline_status_failed", exc_info=True
            )

    async def _publish_positions(self) -> None:
        """Publish current positions from IB to Redis."""
        try:
            connected = False
            try:
                connected = self._ib.isConnected()
            except Exception:
                pass

            if not connected:
                return

            try:
                positions = self._ib.positions()
            except Exception:
                self._log.warning(
                    "dashboard_publisher.positions_fetch_failed", exc_info=True
                )
                return

            serialized = []
            for pos in positions:
                try:
                    entry = {
                        "symbol": getattr(pos.contract, "symbol", ""),
                        "sec_type": getattr(pos.contract, "secType", ""),
                        "quantity": float(pos.position),
                        "avg_cost": float(pos.avgCost),
                    }
                    serialized.append(entry)
                except Exception:
                    continue

            positions_json = json.dumps(serialized)
            await self._redis.set("dashboard:positions", positions_json)
            await self._redis.publish("dashboard:positions", positions_json)
        except Exception:
            self._log.warning(
                "dashboard_publisher.positions_failed", exc_info=True
            )

    async def _publish_portfolio_greeks(self) -> None:
        """Aggregate Greeks from Redis and publish portfolio-level totals.

        Scans Redis for all mktdata:latest:greeks:* keys, sums delta/gamma/
        theta/vega across all option contracts, and publishes the aggregate
        as the portfolio Greeks snapshot.
        """
        try:
            sum_delta = 0.0
            sum_gamma = 0.0
            sum_theta = 0.0
            sum_vega = 0.0
            count = 0

            # Use SCAN instead of KEYS for production safety
            cursor = 0
            while True:
                cursor, keys = await self._redis.scan(
                    cursor=cursor,
                    match="mktdata:latest:greeks:*",
                    count=100,
                )
                for key in keys:
                    try:
                        data = await self._redis.hgetall(key)
                        if data:
                            sum_delta += float(data.get("delta", 0))
                            sum_gamma += float(data.get("gamma", 0))
                            sum_theta += float(data.get("theta", 0))
                            sum_vega += float(data.get("vega", 0))
                            count += 1
                    except (ValueError, TypeError):
                        continue

                if cursor == 0:
                    break

            greeks_blob = json.dumps({
                "delta": round(sum_delta, 10),
                "gamma": round(sum_gamma, 10),
                "theta": round(sum_theta, 10),
                "vega": round(sum_vega, 10),
                "is_portfolio": True,
                "contract_count": count,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            await self._redis.set("dashboard:portfolio_greeks", greeks_blob)
            await self._redis.publish("dashboard:portfolio_greeks", greeks_blob)
        except Exception:
            self._log.warning(
                "dashboard_publisher.portfolio_greeks_failed", exc_info=True
            )
