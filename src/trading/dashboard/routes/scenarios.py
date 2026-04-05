"""REST endpoint for what-if scenario analysis.

Provides POST /api/scenarios which re-prices all open option positions
under hypothetical market conditions using the Black-Scholes pricing
engine. Resolves contract details from Redis cache or OCC symbol
parsing for positions that lack explicit strike/expiry data.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Request

from trading.dashboard.models import ScenarioRequest, ScenarioResponse
from trading.dashboard.scenario_engine import scenario_pnl

logger = structlog.get_logger().bind(component="scenarios_routes")

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


def _parse_occ_symbol(symbol: str) -> dict | None:
    """Parse an OCC-format option symbol into contract details.

    OCC format: SYMBOL  YYMMDDCNNNNNPPP (right-padded symbol to 6 chars,
    then date, then C/P, then strike * 1000 with leading zeros).

    Example: SPY   260417C00500000 -> SPY, 2026-04-17, C, 500.00

    Args:
        symbol: OCC-format option symbol string.

    Returns:
        Dict with underlying, expiry, right, strike, or None if not parseable.
    """
    # OCC standard: 6-char padded symbol + 6-char date + 1-char right + 8-char strike
    # Total = 21 chars, but symbol padding varies. Use regex instead.
    match = re.match(
        r"^([A-Z]+)\s*(\d{6})([CP])(\d{8})$",
        symbol.strip(),
    )
    if not match:
        return None

    underlying = match.group(1)
    date_str = match.group(2)
    right = match.group(3)
    strike_raw = match.group(4)

    try:
        expiry = datetime.strptime(date_str, "%y%m%d").replace(tzinfo=timezone.utc)
        strike = int(strike_raw) / 1000.0
    except (ValueError, TypeError):
        return None

    return {
        "underlying": underlying,
        "expiry": expiry,
        "right": right,
        "strike": strike,
    }


async def _resolve_contract_details(
    redis_client, position: dict
) -> dict | None:
    """Resolve contract details for an option position.

    Attempts resolution in order:
    1. Redis contract cache (contractcache:{con_id} or contractcache:{symbol})
    2. OCC symbol parsing
    3. Inline fields already present on the position

    Args:
        redis_client: Async Redis client.
        position: Position dict from dashboard:positions.

    Returns:
        Dict with underlying_price, strike, dte, implied_vol, right,
        or None if unresolvable.
    """
    symbol = position.get("symbol", "")
    sec_type = position.get("sec_type", "")
    con_id = position.get("con_id", "")

    # Only process options
    if sec_type != "OPT":
        return None

    strike = position.get("strike")
    right = position.get("right")
    expiry_str = position.get("expiry") or position.get("last_trade_date")
    underlying = position.get("underlying", "")

    # Strategy 1: Try Redis contract cache
    if not all([strike, right, expiry_str]):
        cache_key = f"contractcache:{con_id}" if con_id else f"contractcache:{symbol}"
        try:
            cached = await redis_client.hgetall(cache_key)
            if cached:
                strike = strike or cached.get("strike")
                right = right or cached.get("right")
                expiry_str = expiry_str or cached.get("expiry") or cached.get("lastTradeDateOrContractMonth")
                underlying = underlying or cached.get("underlying") or cached.get("symbol", "")
        except Exception:
            logger.debug("scenario.contract_cache_miss", symbol=symbol)

    # Strategy 2: Try OCC symbol parsing
    if not all([strike, right, expiry_str]):
        occ = _parse_occ_symbol(symbol)
        if occ:
            strike = strike or occ["strike"]
            right = right or occ["right"]
            expiry_str = expiry_str or occ["expiry"].strftime("%Y%m%d")
            underlying = underlying or occ["underlying"]

    # Check we have minimum required fields
    if not all([strike, right]):
        return None

    # Compute DTE
    dte = 30  # default if no expiry
    if expiry_str:
        try:
            if isinstance(expiry_str, str):
                # Try multiple date formats
                for fmt in ("%Y%m%d", "%Y-%m-%d", "%y%m%d"):
                    try:
                        expiry_dt = datetime.strptime(expiry_str, fmt).replace(
                            tzinfo=timezone.utc
                        )
                        dte = max((expiry_dt - datetime.now(timezone.utc)).days, 0)
                        break
                    except ValueError:
                        continue
        except Exception:
            pass

    # Get underlying price from market data
    underlying_price = None
    lookup_symbol = underlying or symbol.split()[0] if " " in symbol else symbol
    # For options, try to find the underlying's quote
    for key_candidate in [
        f"mktdata:latest:quote:{underlying}" if underlying else None,
        f"mktdata:latest:quote:{lookup_symbol}",
    ]:
        if not key_candidate:
            continue
        try:
            quote = await redis_client.hgetall(key_candidate)
            if quote:
                last = quote.get("last")
                if last is not None and last != "":
                    underlying_price = float(last)
                    break
                bid = quote.get("bid")
                ask = quote.get("ask")
                if bid is not None and ask is not None:
                    try:
                        underlying_price = (float(bid) + float(ask)) / 2.0
                        break
                    except (ValueError, TypeError):
                        pass
        except Exception:
            pass

    if underlying_price is None:
        return None

    # Get IV from Greeks data if available
    implied_vol = position.get("implied_vol") or position.get("iv")
    if not implied_vol and con_id:
        try:
            greeks_data = await redis_client.hgetall(f"mktdata:latest:greeks:{con_id}")
            if greeks_data:
                iv_val = greeks_data.get("impliedVol") or greeks_data.get("implied_vol")
                if iv_val:
                    implied_vol = float(iv_val)
        except Exception:
            pass

    # Default IV if still not found
    if not implied_vol:
        implied_vol = 0.25  # 25% as reasonable default

    return {
        "underlying_price": underlying_price,
        "strike": float(strike),
        "dte": dte,
        "implied_vol": float(implied_vol),
        "right": right,
        "symbol": underlying or symbol,
    }


@router.post("", response_model=ScenarioResponse)
async def run_scenario(request: Request, params: ScenarioRequest) -> ScenarioResponse:
    """Run what-if scenario analysis on current portfolio.

    Fetches positions from Redis, resolves contract details for each
    option position, and runs the Black-Scholes scenario engine to
    compute hypothetical P&L under the specified market conditions.

    Args:
        request: FastAPI request (provides Redis client via app.state).
        params: Scenario parameters (underlying change, IV change, days forward).

    Returns:
        ScenarioResponse with current/scenario values, P&L, and per-position breakdown.
    """
    redis_client = request.app.state.redis

    # Fetch current positions from Redis
    try:
        raw = await redis_client.get("dashboard:positions")
    except Exception:
        logger.warning("scenario.redis_read_failed", exc_info=True)
        return ScenarioResponse(
            current_value=0.0,
            scenario_value=0.0,
            pnl=0.0,
            pnl_percent=0.0,
            per_position=[],
        )

    if not raw:
        return ScenarioResponse(
            current_value=0.0,
            scenario_value=0.0,
            pnl=0.0,
            pnl_percent=0.0,
            per_position=[],
        )

    try:
        entries = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("scenario.json_parse_failed")
        return ScenarioResponse(
            current_value=0.0,
            scenario_value=0.0,
            pnl=0.0,
            pnl_percent=0.0,
            per_position=[],
        )

    # Resolve contract details and build positions list
    resolved_positions = []
    skipped_symbols = []

    for entry in entries:
        sec_type = entry.get("sec_type", "")
        if sec_type != "OPT":
            # Skip non-option positions for scenario analysis
            continue

        details = await _resolve_contract_details(redis_client, entry)
        if details is None:
            skipped_symbols.append({
                "symbol": entry.get("symbol", "?"),
                "reason": "Could not resolve contract details",
            })
            continue

        resolved_positions.append({
            **details,
            "quantity": float(entry.get("quantity", 0)),
            "multiplier": float(entry.get("multiplier", 100)),
        })

    # Run scenario analysis
    result = scenario_pnl(
        positions=resolved_positions,
        underlying_change_pct=params.underlying_change_pct,
        iv_change_pct=params.iv_change_pct,
        days_forward=params.days_forward,
        risk_free_rate=params.risk_free_rate,
    )

    # Merge skipped from engine with resolution skips
    all_skipped = skipped_symbols + result.get("skipped", [])

    logger.info(
        "scenario.computed",
        num_positions=len(resolved_positions),
        num_skipped=len(all_skipped),
        pnl=result["pnl"],
        pnl_percent=result["pnl_percent"],
    )

    # Add skipped info to per_position if any
    per_position_output = result["per_position"]
    if all_skipped:
        for s in all_skipped:
            per_position_output.append({
                "symbol": s.get("symbol", "?"),
                "status": "skipped",
                "reason": s.get("reason", "unknown"),
            })

    return ScenarioResponse(
        current_value=result["current_value"],
        scenario_value=result["scenario_value"],
        pnl=result["pnl"],
        pnl_percent=result["pnl_percent"],
        per_position=per_position_output,
    )
