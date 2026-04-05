"""Health status REST endpoint for system monitoring.

Provides a comprehensive health status endpoint that checks IB connection,
database connectivity, Redis connectivity, data stream freshness,
pipeline status, heartbeat, and per-agent last-seen timestamps from
the AgentDecisionLog table.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trading.dashboard.deps import get_db_session
from trading.db.models import AgentDecisionLog

logger = structlog.get_logger().bind(component="health_route")

router = APIRouter(prefix="/api/health", tags=["health"])


class HealthStatus(BaseModel):
    """Comprehensive system health status response."""

    ib_connected: bool
    db_connected: bool
    redis_connected: bool
    data_freshness: dict[str, float]
    last_heartbeat: str | None
    pipeline_status: str
    agent_last_seen: dict[str, str]


async def _check_redis(request: Request) -> bool:
    """Check Redis connectivity via PING.

    Returns:
        True if Redis responds to PING, False otherwise.
    """
    try:
        redis = request.app.state.redis
        await redis.ping()
        return True
    except Exception:
        logger.warning("health.redis_check_failed", exc_info=True)
        return False


async def _check_db(session: AsyncSession) -> bool:
    """Check database connectivity via SELECT 1.

    Returns:
        True if DB responds, False otherwise.
    """
    try:
        from sqlalchemy import text

        await session.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.warning("health.db_check_failed", exc_info=True)
        return False


async def _get_ib_status(request: Request) -> bool:
    """Read IB connection status from Redis.

    The DashboardPublisher writes "connected" or "disconnected"
    to the dashboard:ib_status key.

    Returns:
        True if IB is connected, False otherwise.
    """
    try:
        redis = request.app.state.redis
        status = await redis.get("dashboard:ib_status")
        return status == "connected"
    except Exception:
        logger.warning("health.ib_status_check_failed", exc_info=True)
        return False


async def _get_data_freshness(request: Request) -> dict[str, float]:
    """Compute per-symbol data freshness from Redis market data keys.

    Scans mktdata:latest:quote:* keys, reads the timestamp field,
    and computes seconds since the last update for each symbol.

    Returns:
        Mapping of symbol to staleness in seconds.
    """
    freshness: dict[str, float] = {}
    now = datetime.now(timezone.utc)

    try:
        redis = request.app.state.redis
        cursor = 0
        while True:
            cursor, keys = await redis.scan(
                cursor=cursor,
                match="mktdata:latest:quote:*",
                count=100,
            )
            for key in keys:
                try:
                    data = await redis.hgetall(key)
                    if not data:
                        continue

                    # Extract symbol from key: mktdata:latest:quote:{symbol}
                    symbol = key.split(":")[-1] if isinstance(key, str) else key.decode().split(":")[-1]

                    ts_str = data.get("timestamp") or data.get("ts")
                    if ts_str:
                        ts = datetime.fromisoformat(ts_str)
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        staleness = (now - ts).total_seconds()
                        freshness[symbol] = round(staleness, 1)
                    else:
                        # No timestamp -- mark as unknown staleness
                        freshness[symbol] = -1.0
                except (ValueError, TypeError, AttributeError):
                    continue

            if cursor == 0:
                break

    except Exception:
        logger.warning("health.data_freshness_failed", exc_info=True)

    return freshness


async def _get_pipeline_status(request: Request) -> str:
    """Read pipeline status from Redis.

    Returns:
        Pipeline status string (idle, running, error).
    """
    try:
        redis = request.app.state.redis
        status = await redis.get("dashboard:pipeline_status")
        return status or "unknown"
    except Exception:
        logger.warning("health.pipeline_status_failed", exc_info=True)
        return "unknown"


async def _get_heartbeat(request: Request) -> str | None:
    """Read last heartbeat timestamp from Redis.

    Returns:
        ISO timestamp string or None.
    """
    try:
        redis = request.app.state.redis
        return await redis.get("dashboard:heartbeat")
    except Exception:
        logger.warning("health.heartbeat_failed", exc_info=True)
        return None


async def _get_agent_last_seen(session: AsyncSession) -> dict[str, str]:
    """Query per-agent last-seen timestamps from AgentDecisionLog.

    Groups by agent_name and returns the max timestamp for each agent,
    giving visibility into when each pipeline agent last ran.

    Returns:
        Mapping of agent_name to ISO timestamp string.
    """
    try:
        stmt = (
            select(
                AgentDecisionLog.agent_name,
                func.max(AgentDecisionLog.timestamp).label("last_seen"),
            )
            .group_by(AgentDecisionLog.agent_name)
        )
        result = await session.execute(stmt)
        rows = result.all()

        agent_map: dict[str, str] = {}
        for row in rows:
            name = row[0]
            last_seen = row[1]
            if last_seen is not None:
                if isinstance(last_seen, datetime):
                    agent_map[name] = last_seen.isoformat()
                else:
                    agent_map[name] = str(last_seen)

        return agent_map
    except Exception:
        logger.warning("health.agent_last_seen_failed", exc_info=True)
        return {}


@router.get("/status", response_model=HealthStatus)
async def health_status(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> HealthStatus:
    """Return comprehensive system health status.

    Checks Redis, DB, and IB connectivity. Computes per-symbol data
    freshness. Reads pipeline status and heartbeat from Redis.
    Queries AgentDecisionLog for per-agent last-seen timestamps.

    Returns:
        HealthStatus with connection status, freshness, and agent activity.
    """
    redis_ok = await _check_redis(request)
    db_ok = await _check_db(session)
    ib_ok = await _get_ib_status(request)
    freshness = await _get_data_freshness(request)
    pipeline = await _get_pipeline_status(request)
    heartbeat = await _get_heartbeat(request)
    agents = await _get_agent_last_seen(session)

    return HealthStatus(
        ib_connected=ib_ok,
        db_connected=db_ok,
        redis_connected=redis_ok,
        data_freshness=freshness,
        last_heartbeat=heartbeat,
        pipeline_status=pipeline,
        agent_last_seen=agents,
    )
