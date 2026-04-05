"""Black-Scholes pricing engine and scenario P&L analysis.

Provides theoretical option pricing via the standard Black-Scholes
formula and a scenario_pnl function that re-prices all open positions
under hypothetical market conditions (underlying price change, IV
change, and time passage).

Used by the /api/scenarios endpoint for what-if portfolio analysis.
"""

from __future__ import annotations

import math

from scipy.stats import norm


def black_scholes_price(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str,
) -> float:
    """Calculate theoretical option price using Black-Scholes formula.

    Args:
        S: Current underlying price.
        K: Strike price.
        T: Time to expiration in years.
        r: Risk-free interest rate (annualized, e.g. 0.05 for 5%).
        sigma: Implied volatility (annualized, e.g. 0.2 for 20%).
        option_type: "C" for call, "P" for put.

    Returns:
        Theoretical option price. Returns intrinsic value if T <= 0.
    """
    is_call = option_type.upper() in ("C", "CALL")

    # At or past expiration: return intrinsic value
    if T <= 0:
        if is_call:
            return max(S - K, 0.0)
        return max(K - S, 0.0)

    # Guard against zero or negative volatility
    if sigma <= 0:
        if is_call:
            return max(S - K * math.exp(-r * T), 0.0)
        return max(K * math.exp(-r * T) - S, 0.0)

    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    if is_call:
        price = S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    else:
        price = K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

    return max(price, 0.0)


def scenario_pnl(
    positions: list[dict],
    underlying_change_pct: float,
    iv_change_pct: float,
    days_forward: int,
    risk_free_rate: float = 0.05,
) -> dict:
    """Compute portfolio P&L under a hypothetical scenario.

    For each position, computes the current theoretical value and the
    scenario theoretical value (after applying the underlying price
    change, IV change, and time passage), then calculates the P&L
    difference.

    Args:
        positions: List of position dicts with keys:
            - underlying_price: Current price of underlying
            - strike: Option strike price
            - dte: Days to expiration
            - implied_vol: Current implied volatility (annualized)
            - quantity: Number of contracts (signed: positive=long, negative=short)
            - multiplier: Contract multiplier (typically 100 for options)
            - right: "C" or "P"
            - symbol: Underlying symbol (for display)
        underlying_change_pct: Percentage change in underlying (e.g. 5.0 for +5%).
        iv_change_pct: Percentage change in IV (e.g. -10.0 for -10%).
        days_forward: Number of days to advance.
        risk_free_rate: Annualized risk-free rate.

    Returns:
        Dict with: current_value, scenario_value, pnl, pnl_percent,
        per_position (list), skipped (list).
    """
    if not positions:
        return {
            "current_value": 0.0,
            "scenario_value": 0.0,
            "pnl": 0.0,
            "pnl_percent": 0.0,
            "per_position": [],
            "skipped": [],
        }

    total_current = 0.0
    total_scenario = 0.0
    per_position = []
    skipped = []

    for pos in positions:
        try:
            S = float(pos["underlying_price"])
            K = float(pos["strike"])
            dte = float(pos["dte"])
            sigma = float(pos["implied_vol"])
            qty = float(pos["quantity"])
            multiplier = float(pos.get("multiplier", 100))
            right = pos.get("right", "C")
            symbol = pos.get("symbol", "?")
        except (KeyError, TypeError, ValueError) as exc:
            skipped.append({
                "symbol": pos.get("symbol", "?"),
                "reason": f"Missing or invalid field: {exc}",
            })
            continue

        # Current theoretical value
        T_current = max(dte / 365.0, 0.0)
        current_price = black_scholes_price(S, K, T_current, risk_free_rate, sigma, right)

        # Scenario values
        S_scenario = S * (1.0 + underlying_change_pct / 100.0)
        sigma_scenario = sigma * (1.0 + iv_change_pct / 100.0)
        sigma_scenario = max(sigma_scenario, 0.001)  # Floor at 0.1%
        T_scenario = max((dte - days_forward) / 365.0, 0.0)

        scenario_price = black_scholes_price(
            S_scenario, K, T_scenario, risk_free_rate, sigma_scenario, right
        )

        # Position-level values (price * quantity * multiplier)
        pos_current = current_price * qty * multiplier
        pos_scenario = scenario_price * qty * multiplier
        pos_pnl = pos_scenario - pos_current

        total_current += pos_current
        total_scenario += pos_scenario

        per_position.append({
            "symbol": symbol,
            "right": right,
            "strike": K,
            "dte": dte,
            "quantity": qty,
            "current_price": round(current_price, 4),
            "scenario_price": round(scenario_price, 4),
            "current_value": round(pos_current, 2),
            "scenario_value": round(pos_scenario, 2),
            "pnl": round(pos_pnl, 2),
        })

    total_pnl = total_scenario - total_current
    pnl_pct = (total_pnl / abs(total_current) * 100.0) if total_current != 0 else 0.0

    return {
        "current_value": round(total_current, 2),
        "scenario_value": round(total_scenario, 2),
        "pnl": round(total_pnl, 2),
        "pnl_percent": round(pnl_pct, 2),
        "per_position": per_position,
        "skipped": skipped,
    }
