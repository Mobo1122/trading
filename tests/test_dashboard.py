"""Tests for the dashboard server, WebSocket manager, Redis bridge, and REST endpoints.

Covers ChannelManager subscribe/unsubscribe/broadcast with dead connection cleanup,
RedisBridge channel mapping, positions REST endpoint, and health check endpoint.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from trading.dashboard.ws.manager import ChannelManager
from trading.dashboard.ws.bridge import RedisBridge


# ---------------------------------------------------------------------------
# ChannelManager tests
# ---------------------------------------------------------------------------


class TestChannelManager:
    """Tests for WebSocket channel subscription manager."""

    @pytest.fixture
    def manager(self) -> ChannelManager:
        return ChannelManager()

    @pytest.fixture
    def mock_ws(self) -> AsyncMock:
        """Create a mock WebSocket connection."""
        ws = AsyncMock()
        ws.send_text = AsyncMock()
        return ws

    @pytest.mark.asyncio
    async def test_subscribe_adds_ws_to_channel(self, manager, mock_ws):
        """Subscribe should add the WebSocket to the specified channel."""
        await manager.subscribe(mock_ws, "quotes:SPY")

        assert manager.active_connections == 1
        assert mock_ws in manager._subscriptions["quotes:SPY"]
        assert "quotes:SPY" in manager._ws_channels[mock_ws]

    @pytest.mark.asyncio
    async def test_subscribe_multiple_channels(self, manager, mock_ws):
        """A single WebSocket can subscribe to multiple channels."""
        await manager.subscribe(mock_ws, "quotes:SPY")
        await manager.subscribe(mock_ws, "quotes:AAPL")

        assert manager.active_connections == 1
        assert len(manager._ws_channels[mock_ws]) == 2

    @pytest.mark.asyncio
    async def test_subscribe_multiple_ws_same_channel(self, manager):
        """Multiple WebSockets can subscribe to the same channel."""
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        await manager.subscribe(ws1, "positions")
        await manager.subscribe(ws2, "positions")

        assert manager.active_connections == 2
        assert len(manager._subscriptions["positions"]) == 2

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_ws_from_channel(self, manager, mock_ws):
        """Unsubscribe should remove the WebSocket from the channel."""
        await manager.subscribe(mock_ws, "quotes:SPY")
        await manager.unsubscribe(mock_ws, "quotes:SPY")

        assert "quotes:SPY" not in manager._subscriptions
        assert manager.active_connections == 0

    @pytest.mark.asyncio
    async def test_unsubscribe_all_removes_from_all_channels(self, manager, mock_ws):
        """unsubscribe_all should remove WebSocket from every channel."""
        await manager.subscribe(mock_ws, "quotes:SPY")
        await manager.subscribe(mock_ws, "positions")
        await manager.subscribe(mock_ws, "health")

        await manager.unsubscribe_all(mock_ws)

        assert manager.active_connections == 0
        assert "quotes:SPY" not in manager._subscriptions
        assert "positions" not in manager._subscriptions
        assert "health" not in manager._subscriptions

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_subscribers(self, manager):
        """Broadcast should send message to all channel subscribers."""
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        ws1.send_text = AsyncMock()
        ws2.send_text = AsyncMock()

        await manager.subscribe(ws1, "quotes:SPY")
        await manager.subscribe(ws2, "quotes:SPY")

        msg = json.dumps({"type": "update", "data": {"price": 450.0}})
        await manager.broadcast("quotes:SPY", msg)

        ws1.send_text.assert_called_once_with(msg)
        ws2.send_text.assert_called_once_with(msg)

    @pytest.mark.asyncio
    async def test_broadcast_no_subscribers(self, manager):
        """Broadcast to a channel with no subscribers should be a no-op."""
        await manager.broadcast("nonexistent", '{"type":"update"}')
        # No error, no crash

    @pytest.mark.asyncio
    async def test_broadcast_cleans_dead_connections(self, manager):
        """Dead connections should be removed during broadcast."""
        ws_alive = AsyncMock()
        ws_alive.send_text = AsyncMock()

        ws_dead = AsyncMock()
        ws_dead.send_text = AsyncMock(side_effect=Exception("Connection closed"))

        await manager.subscribe(ws_alive, "positions")
        await manager.subscribe(ws_dead, "positions")

        assert manager.active_connections == 2

        await manager.broadcast("positions", '{"type":"update"}')

        # Dead connection should have been cleaned up
        assert manager.active_connections == 1
        ws_alive.send_text.assert_called_once()


# ---------------------------------------------------------------------------
# RedisBridge._map_channel tests
# ---------------------------------------------------------------------------


class TestRedisBridgeChannelMapping:
    """Tests for Redis channel to dashboard topic mapping."""

    @pytest.fixture
    def bridge(self) -> RedisBridge:
        """Create a RedisBridge with mocked dependencies."""
        redis = AsyncMock()
        channel_manager = AsyncMock()
        return RedisBridge(
            redis=redis,
            channel_manager=channel_manager,
            throttle_ms=500,
        )

    def test_map_quote_channel(self, bridge):
        """mktdata:quote:SPY should map to quotes:SPY."""
        assert bridge._map_channel("mktdata:quote:SPY") == "quotes:SPY"

    def test_map_quote_channel_different_symbol(self, bridge):
        """mktdata:quote:AAPL should map to quotes:AAPL."""
        assert bridge._map_channel("mktdata:quote:AAPL") == "quotes:AAPL"

    def test_map_greeks_channel(self, bridge):
        """mktdata:greeks:SPY:12345 should map to greeks:SPY:12345."""
        assert bridge._map_channel("mktdata:greeks:SPY:12345") == "greeks:SPY:12345"

    def test_map_stale_channel(self, bridge):
        """mktdata:stale should map to staleness."""
        assert bridge._map_channel("mktdata:stale") == "staleness"

    def test_map_positions_channel(self, bridge):
        """dashboard:positions should map to positions."""
        assert bridge._map_channel("dashboard:positions") == "positions"

    def test_map_health_channel(self, bridge):
        """dashboard:health should map to health."""
        assert bridge._map_channel("dashboard:health") == "health"

    def test_map_portfolio_greeks_channel(self, bridge):
        """dashboard:portfolio_greeks should map to portfolio_greeks."""
        assert bridge._map_channel("dashboard:portfolio_greeks") == "portfolio_greeks"

    def test_map_unknown_channel_returns_none(self, bridge):
        """Unknown channels should return None."""
        assert bridge._map_channel("unknown:channel") is None

    def test_map_empty_string_returns_none(self, bridge):
        """Empty string should return None."""
        assert bridge._map_channel("") is None


# ---------------------------------------------------------------------------
# REST endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_endpoint():
    """GET /api/health should return {"status": "ok"}."""
    from trading.dashboard.server import create_app

    # httpx is used for async testing of FastAPI apps
    try:
        from httpx import AsyncClient, ASGITransport
    except ImportError:
        pytest.skip("httpx not installed")

    app = create_app()

    # Mock app.state resources to avoid real connections
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.close = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.scan = AsyncMock(return_value=(0, []))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_positions_endpoint_empty():
    """GET /api/positions with no cached data should return empty list."""
    from trading.dashboard.server import create_app

    try:
        from httpx import AsyncClient, ASGITransport
    except ImportError:
        pytest.skip("httpx not installed")

    app = create_app()

    # Override Redis in app.state via lifespan mock
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.hgetall = AsyncMock(return_value={})
    mock_redis.close = AsyncMock()

    # Inject mock redis before request
    app.state.redis = mock_redis

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 0


@pytest.mark.asyncio
async def test_positions_endpoint_with_data():
    """GET /api/positions with cached positions should return enriched data."""
    from trading.dashboard.server import create_app

    try:
        from httpx import AsyncClient, ASGITransport
    except ImportError:
        pytest.skip("httpx not installed")

    app = create_app()

    positions_data = json.dumps([
        {
            "symbol": "SPY",
            "sec_type": "STK",
            "quantity": 100,
            "avg_cost": 450.0,
        },
        {
            "symbol": "AAPL",
            "sec_type": "OPT",
            "quantity": 5,
            "avg_cost": 3.50,
        },
    ])

    mock_redis = AsyncMock()
    mock_redis.close = AsyncMock()

    async def mock_get(key):
        if key == "dashboard:positions":
            return positions_data
        return None

    async def mock_hgetall(key):
        if key == "mktdata:latest:quote:SPY":
            return {"last": "455.0", "bid": "454.8", "ask": "455.2"}
        if key == "mktdata:latest:quote:AAPL":
            return {"last": "4.00", "bid": "3.90", "ask": "4.10"}
        return {}

    mock_redis.get = AsyncMock(side_effect=mock_get)
    mock_redis.hgetall = AsyncMock(side_effect=mock_hgetall)

    app.state.redis = mock_redis

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

        # SPY: stock, multiplier=1, P&L = (455 - 450) * 100 * 1 = 500
        spy = next(p for p in data if p["symbol"] == "SPY")
        assert spy["quantity"] == 100
        assert spy["current_price"] == 455.0
        assert spy["unrealized_pnl"] == 500.0
        assert spy["market_value"] == 45500.0

        # AAPL: option, multiplier=100, P&L = (4.00 - 3.50) * 5 * 100 = 250
        aapl = next(p for p in data if p["symbol"] == "AAPL")
        assert aapl["quantity"] == 5
        assert aapl["current_price"] == 4.00
        assert aapl["unrealized_pnl"] == 250.0
        assert aapl["market_value"] == 2000.0


@pytest.mark.asyncio
async def test_portfolio_endpoint():
    """GET /api/portfolio should return aggregated portfolio summary."""
    from trading.dashboard.server import create_app

    try:
        from httpx import AsyncClient, ASGITransport
    except ImportError:
        pytest.skip("httpx not installed")

    app = create_app()

    positions_data = json.dumps([
        {
            "symbol": "SPY",
            "sec_type": "STK",
            "quantity": 100,
            "avg_cost": 450.0,
        },
    ])

    mock_redis = AsyncMock()
    mock_redis.close = AsyncMock()

    async def mock_get(key):
        if key == "dashboard:positions":
            return positions_data
        if key == "dashboard:realized_pnl":
            return "1500.0"
        return None

    async def mock_hgetall(key):
        if key == "mktdata:latest:quote:SPY":
            return {"last": "455.0"}
        return {}

    mock_redis.get = AsyncMock(side_effect=mock_get)
    mock_redis.hgetall = AsyncMock(side_effect=mock_hgetall)

    app.state.redis = mock_redis

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/portfolio")
        assert resp.status_code == 200
        data = resp.json()

        # SPY: market_value = 455 * 100 = 45500, P&L = 500
        assert data["total_market_value"] == 45500.0
        assert data["total_unrealized_pnl"] == 500.0
        assert data["total_realized_pnl"] == 1500.0
        # Net liq = market_value + unrealized + realized = 45500 + 500 + 1500
        assert data["net_liquidation"] == 47500.0


# ---------------------------------------------------------------------------
# Scenario engine tests
# ---------------------------------------------------------------------------


class TestBlackScholesPrice:
    """Tests for Black-Scholes option pricing."""

    def test_atm_call_price_reasonable(self):
        """ATM call with 3 months to expiry should be in reasonable range."""
        from trading.dashboard.scenario_engine import black_scholes_price

        price = black_scholes_price(100, 100, 0.25, 0.05, 0.2, "C")
        # ATM call with 20% vol, 3 months: ~$4-6
        assert 3.0 < price < 7.0, f"ATM call price {price} out of range"

    def test_atm_put_price_reasonable(self):
        """ATM put with 3 months to expiry should be in reasonable range."""
        from trading.dashboard.scenario_engine import black_scholes_price

        price = black_scholes_price(100, 100, 0.25, 0.05, 0.2, "P")
        assert 2.0 < price < 6.0, f"ATM put price {price} out of range"

    def test_itm_put_at_expiration(self):
        """ITM put at expiration should return intrinsic value."""
        from trading.dashboard.scenario_engine import black_scholes_price

        # Put: K=100, S=95 -> intrinsic = 5.0
        price = black_scholes_price(95, 100, 0, 0.05, 0.3, "P")
        assert price == 5.0

    def test_call_at_expiration_intrinsic(self):
        """ITM call at expiration should return intrinsic value."""
        from trading.dashboard.scenario_engine import black_scholes_price

        price = black_scholes_price(105, 100, 0, 0.05, 0.2, "C")
        assert price == 5.0

    def test_otm_call_at_expiration_zero(self):
        """OTM call at expiration should return zero."""
        from trading.dashboard.scenario_engine import black_scholes_price

        price = black_scholes_price(95, 100, 0, 0.05, 0.2, "C")
        assert price == 0.0

    def test_otm_put_at_expiration_zero(self):
        """OTM put at expiration should return zero."""
        from trading.dashboard.scenario_engine import black_scholes_price

        price = black_scholes_price(105, 100, 0, 0.05, 0.2, "P")
        assert price == 0.0

    def test_deep_itm_call_approaches_intrinsic(self):
        """Deep ITM call should approach intrinsic value."""
        from trading.dashboard.scenario_engine import black_scholes_price

        price = black_scholes_price(150, 100, 0.25, 0.05, 0.2, "C")
        intrinsic = 50.0
        assert price >= intrinsic, f"Deep ITM call {price} < intrinsic {intrinsic}"

    def test_zero_vol_returns_intrinsic_discounted(self):
        """Zero volatility should return discounted intrinsic value."""
        from trading.dashboard.scenario_engine import black_scholes_price

        price = black_scholes_price(110, 100, 1.0, 0.05, 0.0, "C")
        # With zero vol, call = max(S - K*exp(-rT), 0)
        import math

        expected = max(110 - 100 * math.exp(-0.05), 0)
        assert abs(price - expected) < 0.01


class TestScenarioPnl:
    """Tests for portfolio scenario P&L analysis."""

    def _make_position(self, **overrides):
        """Helper to create a test position dict."""
        defaults = {
            "underlying_price": 100,
            "strike": 100,
            "dte": 30,
            "implied_vol": 0.2,
            "quantity": 1,
            "multiplier": 100,
            "right": "C",
            "symbol": "SPY",
        }
        defaults.update(overrides)
        return defaults

    def test_call_positive_underlying_move(self):
        """Long call should profit from positive underlying move."""
        from trading.dashboard.scenario_engine import scenario_pnl

        result = scenario_pnl(
            [self._make_position(right="C", quantity=1)],
            underlying_change_pct=5.0,
            iv_change_pct=0.0,
            days_forward=0,
        )
        assert result["pnl"] > 0, f"Call +5% should be positive, got {result['pnl']}"

    def test_put_positive_underlying_move(self):
        """Long put should lose from positive underlying move."""
        from trading.dashboard.scenario_engine import scenario_pnl

        result = scenario_pnl(
            [self._make_position(right="P", quantity=1)],
            underlying_change_pct=5.0,
            iv_change_pct=0.0,
            days_forward=0,
        )
        assert result["pnl"] < 0, f"Put +5% should be negative, got {result['pnl']}"

    def test_empty_positions_returns_zeros(self):
        """Empty positions list should return all zeros."""
        from trading.dashboard.scenario_engine import scenario_pnl

        result = scenario_pnl([], underlying_change_pct=5.0, iv_change_pct=0.0, days_forward=0)
        assert result["current_value"] == 0.0
        assert result["scenario_value"] == 0.0
        assert result["pnl"] == 0.0
        assert result["pnl_percent"] == 0.0
        assert result["per_position"] == []

    def test_theta_decay_reduces_long_call_value(self):
        """Time passage should reduce long call value (theta decay)."""
        from trading.dashboard.scenario_engine import scenario_pnl

        result = scenario_pnl(
            [self._make_position(right="C", quantity=1, dte=30)],
            underlying_change_pct=0.0,
            iv_change_pct=0.0,
            days_forward=7,
        )
        assert result["pnl"] < 0, f"Theta decay should be negative, got {result['pnl']}"

    def test_iv_increase_benefits_long_call(self):
        """IV increase should benefit a long call position (vega)."""
        from trading.dashboard.scenario_engine import scenario_pnl

        result = scenario_pnl(
            [self._make_position(right="C", quantity=1)],
            underlying_change_pct=0.0,
            iv_change_pct=20.0,
            days_forward=0,
        )
        assert result["pnl"] > 0, f"IV increase should be positive for long call, got {result['pnl']}"

    def test_short_call_profits_from_theta(self):
        """Short call should profit from theta decay."""
        from trading.dashboard.scenario_engine import scenario_pnl

        result = scenario_pnl(
            [self._make_position(right="C", quantity=-1, dte=30)],
            underlying_change_pct=0.0,
            iv_change_pct=0.0,
            days_forward=7,
        )
        assert result["pnl"] > 0, f"Short call theta should be positive, got {result['pnl']}"

    def test_pnl_percent_calculated(self):
        """P&L percent should be calculated relative to current value."""
        from trading.dashboard.scenario_engine import scenario_pnl

        result = scenario_pnl(
            [self._make_position(right="C", quantity=1)],
            underlying_change_pct=10.0,
            iv_change_pct=0.0,
            days_forward=0,
        )
        assert result["pnl_percent"] != 0.0
        # pnl_percent should equal pnl / abs(current_value) * 100
        if result["current_value"] != 0:
            expected_pct = result["pnl"] / abs(result["current_value"]) * 100
            assert abs(result["pnl_percent"] - round(expected_pct, 2)) < 0.1

    def test_per_position_breakdown(self):
        """Per-position breakdown should contain entry for each position."""
        from trading.dashboard.scenario_engine import scenario_pnl

        result = scenario_pnl(
            [
                self._make_position(right="C", symbol="SPY"),
                self._make_position(right="P", symbol="AAPL", strike=150, underlying_price=155),
            ],
            underlying_change_pct=5.0,
            iv_change_pct=0.0,
            days_forward=0,
        )
        assert len(result["per_position"]) == 2
        symbols = [p["symbol"] for p in result["per_position"]]
        assert "SPY" in symbols
        assert "AAPL" in symbols

    def test_invalid_position_skipped(self):
        """Position with missing fields should be skipped."""
        from trading.dashboard.scenario_engine import scenario_pnl

        result = scenario_pnl(
            [{"symbol": "BAD", "quantity": 1}],
            underlying_change_pct=0.0,
            iv_change_pct=0.0,
            days_forward=0,
        )
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["symbol"] == "BAD"
