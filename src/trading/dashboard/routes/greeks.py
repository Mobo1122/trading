"""Greeks REST endpoints for the dashboard API.

Provides portfolio-level aggregated Greeks and per-position Greeks
breakdown. Data is sourced from Redis ``mktdata:latest:greeks:*``
keys written by the Phase 2 market data pipeline.

Routes:
    GET /api/greeks          -- Aggregated portfolio Greeks (delta, gamma, theta, vega).
    GET /api/greeks/positions -- Per-position Greeks breakdown.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request

from trading.dashboard.models import GreeksResponse

logger = structlog.get_logger().bind(component="dashboard_routes_greeks")

router = APIRouter(prefix="/api/greeks", tags=["greeks"])


async def _scan_greeks(redis_client) -> list[dict]:
    """Scan Redis for all option Greeks keys and return raw data.

    Uses SCAN (not KEYS) to avoid blocking Redis on large keyspaces.

    Returns:
        List of dicts with delta, gamma, theta, vega, symbol, and con_id.
    """
    results = []
    cursor = 0
    while True:
        cursor, keys = await redis_client.scan(
            cursor=cursor, match="mktdata:latest:greeks:*", count=100
        )
        for key in keys:
            data = await redis_client.hgetall(key)
            if data:
                # Extract con_id from key: mktdata:latest:greeks:{con_id}
                con_id = key.split(":")[-1] if isinstance(key, str) else ""
                results.append({
                    "delta": float(data.get("delta", 0)),
                    "gamma": float(data.get("gamma", 0)),
                    "theta": float(data.get("theta", 0)),
                    "vega": float(data.get("vega", 0)),
                    "symbol": data.get("symbol", ""),
                    "con_id": con_id,
                })
        if cursor == 0:
            break
    return results


@router.get("", response_model=GreeksResponse)
async def get_portfolio_greeks(request: Request) -> GreeksResponse:
    """Return portfolio-level aggregated Greeks.

    Sums delta, gamma, theta, and vega across all option contracts
    in the portfolio. Values are rounded to 10 decimal places to
    avoid IEEE 754 float noise (consistent with Phase 3 pattern).
    """
    redis_client = request.app.state.redis
    positions = await _scan_greeks(redis_client)

    total_delta = round(sum(p["delta"] for p in positions), 10)
    total_gamma = round(sum(p["gamma"] for p in positions), 10)
    total_theta = round(sum(p["theta"] for p in positions), 10)
    total_vega = round(sum(p["vega"] for p in positions), 10)

    logger.debug(
        "greeks.portfolio",
        num_positions=len(positions),
        delta=total_delta,
        gamma=total_gamma,
        theta=total_theta,
        vega=total_vega,
    )

    return GreeksResponse(
        delta=total_delta,
        gamma=total_gamma,
        theta=total_theta,
        vega=total_vega,
        is_portfolio=True,
    )


@router.get("/positions", response_model=list[GreeksResponse])
async def get_position_greeks(request: Request) -> list[GreeksResponse]:
    """Return per-position Greeks breakdown.

    Each item represents a single option contract's current Greeks.
    """
    redis_client = request.app.state.redis
    positions = await _scan_greeks(redis_client)

    return [
        GreeksResponse(
            delta=p["delta"],
            gamma=p["gamma"],
            theta=p["theta"],
            vega=p["vega"],
            symbol=p["symbol"] or None,
            is_portfolio=False,
        )
        for p in positions
    ]
