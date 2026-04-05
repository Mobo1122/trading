"""REST endpoints for positions and portfolio summary.

Provides GET /api/positions for per-position snapshots with real-time
prices from Redis, and GET /api/portfolio for portfolio-level P&L
aggregation. Both endpoints derive data from the dashboard:positions
Redis key published by DashboardPublisher.
"""

from __future__ import annotations

import json

import structlog
from fastapi import APIRouter, Request

from trading.dashboard.models import PortfolioSummary, PositionResponse

logger = structlog.get_logger().bind(component="positions_routes")

router = APIRouter(prefix="/api", tags=["positions"])


@router.get("/positions", response_model=list[PositionResponse])
async def get_positions(request: Request) -> list[PositionResponse]:
    """Return current positions with real-time prices and P&L.

    Reads the dashboard:positions key from Redis (published by
    DashboardPublisher), enriches each position with the latest
    market price from mktdata:latest:quote:{symbol}, and computes
    unrealized P&L per position.

    Returns:
        List of PositionResponse with current prices and P&L fields.
    """
    redis = request.app.state.redis
    positions: list[PositionResponse] = []

    try:
        raw = await redis.get("dashboard:positions")
    except Exception:
        logger.warning("positions.redis_read_failed", exc_info=True)
        return positions

    if not raw:
        return positions

    try:
        entries = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("positions.json_parse_failed")
        return positions

    for entry in entries:
        symbol = entry.get("symbol", "")
        sec_type = entry.get("sec_type", "")
        quantity = float(entry.get("quantity", 0))
        avg_cost = float(entry.get("avg_cost", 0))

        # Look up real-time price from market data cache
        current_price = None
        try:
            quote_data = await redis.hgetall(f"mktdata:latest:quote:{symbol}")
            if quote_data:
                # Prefer last, then midpoint of bid/ask
                last = quote_data.get("last")
                if last is not None and last != "":
                    current_price = float(last)
                else:
                    bid = quote_data.get("bid")
                    ask = quote_data.get("ask")
                    if bid is not None and ask is not None:
                        try:
                            current_price = (float(bid) + float(ask)) / 2.0
                        except (ValueError, TypeError):
                            pass
        except Exception:
            logger.debug(
                "positions.quote_lookup_failed",
                symbol=symbol,
                exc_info=True,
            )

        # Compute P&L: multiplier is 100 for options (OPT), 1 for stocks (STK)
        multiplier = 100.0 if sec_type == "OPT" else 1.0
        unrealized_pnl = None
        unrealized_pnl_pct = None
        market_value = None

        if current_price is not None and avg_cost > 0:
            unrealized_pnl = (current_price - avg_cost) * quantity * multiplier
            cost_basis = avg_cost * abs(quantity) * multiplier
            if cost_basis > 0:
                unrealized_pnl_pct = (unrealized_pnl / cost_basis) * 100.0
            market_value = current_price * abs(quantity) * multiplier

        positions.append(
            PositionResponse(
                symbol=symbol,
                sec_type=sec_type,
                quantity=int(quantity),
                avg_cost=avg_cost,
                current_price=current_price,
                unrealized_pnl=unrealized_pnl,
                unrealized_pnl_pct=unrealized_pnl_pct,
                market_value=market_value,
            )
        )

    return positions


@router.get("/portfolio", response_model=PortfolioSummary)
async def get_portfolio(request: Request) -> PortfolioSummary:
    """Return portfolio-level P&L summary.

    Aggregates across all positions: total market value, total unrealized
    P&L, total realized P&L (from Redis), and net liquidation value.

    Returns:
        PortfolioSummary with aggregated portfolio metrics.
    """
    redis = request.app.state.redis

    # Get all positions to aggregate
    all_positions = await get_positions(request)

    total_market_value = 0.0
    total_unrealized_pnl = 0.0

    for pos in all_positions:
        if pos.market_value is not None:
            total_market_value += pos.market_value
        if pos.unrealized_pnl is not None:
            total_unrealized_pnl += pos.unrealized_pnl

    # Realized P&L: check Redis for any cached value from execution records
    total_realized_pnl = 0.0
    try:
        realized = await redis.get("dashboard:realized_pnl")
        if realized is not None:
            total_realized_pnl = float(realized)
    except Exception:
        logger.debug("portfolio.realized_pnl_lookup_failed", exc_info=True)

    net_liquidation = total_market_value + total_unrealized_pnl + total_realized_pnl

    return PortfolioSummary(
        total_market_value=round(total_market_value, 2),
        total_unrealized_pnl=round(total_unrealized_pnl, 2),
        total_realized_pnl=round(total_realized_pnl, 2),
        net_liquidation=round(net_liquidation, 2),
    )
