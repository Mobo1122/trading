"""System health monitoring for IB, database, and Redis.

Provides the HealthMonitor class that checks the health of all
critical system components and computes an overall health status.
Used for observability, alerting, and readiness probes.

Health levels:
  - HEALTHY: All components operational
  - DEGRADED: IB disconnected but DB and Redis are up
  - UNHEALTHY: Any critical component (DB or Redis) is down
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import structlog
from sqlalchemy import text

from trading.core.connection import IBConnectionManager


class ComponentHealth(str, enum.Enum):
    """Overall system health status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class HealthStatus:
    """Snapshot of system health at a point in time.

    Attributes:
        ib_connected: Whether the IB Gateway connection is active.
        ib_reconnect_count: Number of IB reconnection attempts since last connect.
        db_connected: Whether the database responds to queries.
        redis_connected: Whether Redis responds to PING.
        trading_mode: Current trading mode (paper/live).
        uptime_seconds: Seconds since the health monitor was created.
        last_check: Timestamp of this health check.
        overall: Computed overall health level.
    """

    ib_connected: bool
    ib_reconnect_count: int
    db_connected: bool
    redis_connected: bool
    trading_mode: str
    uptime_seconds: float
    last_check: datetime
    overall: ComponentHealth


class HealthMonitor:
    """Monitors the health of all system components.

    Checks IB connection state, database connectivity (SELECT 1),
    and Redis connectivity (PING) to compute an overall health status.

    Usage:
        monitor = HealthMonitor(connection_manager, db_engine, redis_client, settings)
        status = await monitor.check_health()
        print(status.overall)  # "healthy", "degraded", or "unhealthy"
    """

    def __init__(
        self,
        connection_manager: IBConnectionManager,
        db_engine,
        redis_client,
        settings,
    ) -> None:
        self._connection_manager = connection_manager
        self._db_engine = db_engine
        self._redis_client = redis_client
        self._settings = settings
        self._start_time = time.monotonic()
        self._logger = structlog.get_logger(component="health_monitor")

    async def check_health(self) -> HealthStatus:
        """Check the health of all system components.

        Checks IB, database, and Redis connectivity and computes
        an overall health level based on the results.

        Returns:
            HealthStatus with current component states and overall health.
        """
        ib_connected = self._connection_manager.is_connected
        ib_reconnect_count = self._connection_manager.reconnect_count

        db_connected = await self._check_db()
        redis_connected = await self._check_redis()

        overall = self._compute_overall(ib_connected, db_connected, redis_connected)

        status = HealthStatus(
            ib_connected=ib_connected,
            ib_reconnect_count=ib_reconnect_count,
            db_connected=db_connected,
            redis_connected=redis_connected,
            trading_mode=self._settings.trading.mode,
            uptime_seconds=time.monotonic() - self._start_time,
            last_check=datetime.now(timezone.utc),
            overall=overall,
        )

        self._logger.info(
            "health_check",
            ib=ib_connected,
            db=db_connected,
            redis=redis_connected,
            overall=overall.value,
        )

        return status

    async def _check_db(self) -> bool:
        """Check database connectivity with SELECT 1.

        Returns:
            True if the database responds, False on any error.
        """
        try:
            async with self._db_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            self._logger.warning("health_check.db_failed", exc_info=True)
            return False

    async def _check_redis(self) -> bool:
        """Check Redis connectivity with PING.

        Returns:
            True if Redis responds to PING, False on any error.
        """
        try:
            result = await self._redis_client.ping()
            return result is True or result == "PONG"
        except Exception:
            self._logger.warning("health_check.redis_failed", exc_info=True)
            return False

    @staticmethod
    def _compute_overall(
        ib_connected: bool,
        db_connected: bool,
        redis_connected: bool,
    ) -> ComponentHealth:
        """Compute overall health from component states.

        Rules:
          - All healthy -> HEALTHY
          - IB disconnected but DB + Redis ok -> DEGRADED
          - Any critical component (DB or Redis) down -> UNHEALTHY

        Args:
            ib_connected: Whether IB is connected.
            db_connected: Whether DB is reachable.
            redis_connected: Whether Redis is reachable.

        Returns:
            Overall ComponentHealth level.
        """
        if not db_connected or not redis_connected:
            return ComponentHealth.UNHEALTHY
        if not ib_connected:
            return ComponentHealth.DEGRADED
        return ComponentHealth.HEALTHY
