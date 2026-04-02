"""Tests for Phase 2 market data streaming pipeline.

Covers QuoteSnapshot/GreeksSnapshot creation from IB Ticker mocks,
NaN-safe float handling, subscription management with LRU eviction,
and Redis distribution with error isolation.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

from trading.market_data.distributor import RedisDistributor
from trading.market_data.models import (
    GreeksSnapshot,
    QuoteSnapshot,
    SubscriptionInfo,
    SubscriptionPriority,
    _safe_float,
)
from trading.market_data.subscriber import SubscriptionManager


# ---- _safe_float tests -------------------------------------------------------


def test_safe_float_nan_returns_none():
    assert _safe_float(float("nan")) is None


def test_safe_float_valid_returns_float():
    assert _safe_float(1.5) == 1.5


def test_safe_float_none_returns_none():
    assert _safe_float(None) is None


def test_safe_float_zero_returns_zero():
    assert _safe_float(0.0) == 0.0


def test_safe_float_negative():
    assert _safe_float(-0.05) == -0.05


# ---- QuoteSnapshot tests -----------------------------------------------------


def _make_ticker(
    symbol="SPY",
    con_id=12345,
    sec_type="STK",
    bid=150.0,
    ask=150.05,
    last=150.02,
):
    """Build a minimal mock Ticker object."""
    ticker = MagicMock()
    ticker.contract.symbol = symbol
    ticker.contract.conId = con_id
    ticker.contract.secType = sec_type
    ticker.bid = bid
    ticker.ask = ask
    ticker.last = last
    ticker.volume = 1_000_000.0
    ticker.putOpenInterest = float("nan")
    ticker.callOpenInterest = float("nan")
    ticker.putVolume = float("nan")
    ticker.callVolume = float("nan")
    ticker.impliedVolatility = float("nan")
    ticker.time = datetime.now(timezone.utc)
    return ticker


def test_quote_snapshot_from_ticker_valid():
    ticker = _make_ticker()
    snapshot = QuoteSnapshot.from_ticker(ticker)
    assert snapshot.symbol == "SPY"
    assert snapshot.con_id == 12345
    assert snapshot.bid == 150.0
    assert snapshot.ask == 150.05
    assert snapshot.last == 150.02
    assert snapshot.volume == 1_000_000.0


def test_quote_snapshot_from_ticker_nan_becomes_none():
    ticker = _make_ticker(bid=float("nan"), ask=float("nan"))
    snapshot = QuoteSnapshot.from_ticker(ticker)
    assert snapshot.bid is None
    assert snapshot.ask is None


def test_quote_snapshot_serialization_no_nan():
    """Serialized JSON must not contain NaN (invalid JSON)."""
    ticker = _make_ticker(bid=float("nan"))
    snapshot = QuoteSnapshot.from_ticker(ticker)
    json_str = snapshot.model_dump_json()
    parsed = json.loads(json_str)  # must not raise
    assert parsed["bid"] is None


def test_quote_snapshot_defaults():
    snapshot = QuoteSnapshot(symbol="AAPL", con_id=111, sec_type="STK")
    assert snapshot.is_stale is False
    assert snapshot.bid is None


# ---- GreeksSnapshot tests -----------------------------------------------------


def _make_option_ticker(
    symbol="AAPL",
    con_id=99999,
    implied_vol=0.25,
    delta=0.45,
):
    ticker = MagicMock()
    ticker.contract.symbol = symbol
    ticker.contract.conId = con_id
    ticker.contract.secType = "OPT"
    ticker.time = datetime.now(timezone.utc)
    greeks = MagicMock()
    greeks.impliedVol = implied_vol
    greeks.delta = delta
    greeks.gamma = 0.02
    greeks.theta = -0.05
    greeks.vega = 0.15
    greeks.undPrice = 150.0
    ticker.modelGreeks = greeks
    return ticker


def test_greeks_snapshot_from_ticker():
    ticker = _make_option_ticker()
    snapshot = GreeksSnapshot.from_ticker(ticker)
    assert snapshot is not None
    assert snapshot.symbol == "AAPL"
    assert snapshot.implied_vol == 0.25
    assert snapshot.delta == 0.45
    assert snapshot.gamma == 0.02


def test_greeks_snapshot_no_greeks_returns_none():
    ticker = MagicMock()
    ticker.modelGreeks = None
    result = GreeksSnapshot.from_ticker(ticker)
    assert result is None


def test_greeks_snapshot_nan_handling():
    ticker = _make_option_ticker(delta=float("nan"))
    snapshot = GreeksSnapshot.from_ticker(ticker)
    assert snapshot.delta is None


# ---- SubscriptionManager tests ------------------------------------------------


def _make_settings(max_lines=100, reserved=20):
    settings = MagicMock()
    settings.market_data.max_subscription_lines = max_lines
    settings.market_data.reserved_lines = reserved
    settings.market_data.watchlist = ["SPY", "QQQ"]
    return settings


def test_subscription_manager_available_lines_starts_at_max():
    ib = MagicMock()
    settings = _make_settings(max_lines=100)
    mgr = SubscriptionManager(ib=ib, settings=settings)
    assert mgr.available_lines == 100
    assert mgr.active_count == 0


def test_subscription_manager_eviction_skips_pinned():
    """LRU eviction must not evict pinned (HIGH priority) subscriptions."""
    ib = MagicMock()
    ib.cancelMktData = MagicMock()
    settings = _make_settings(max_lines=100)
    mgr = SubscriptionManager(ib=ib, settings=settings)

    # Manually add subscriptions to _active and _contracts
    now = datetime.now(timezone.utc)
    for i in range(3):
        con_id = 1000 + i
        info = SubscriptionInfo(
            con_id=con_id,
            symbol=f"SYM{i}",
            sec_type="STK",
            priority=(
                SubscriptionPriority.HIGH if i == 0 else SubscriptionPriority.LOW
            ),
            subscribed_at=now - timedelta(hours=i),
        )
        mgr._active[con_id] = info
        mgr._contracts[con_id] = MagicMock()
        if i == 0:
            mgr._priority_pins.add(con_id)

    # Evict one -- should NOT evict the HIGH priority subscription (con_id=1000)
    result = mgr._evict_one()
    assert result is True
    assert 1000 in mgr._active  # HIGH priority was NOT evicted
    assert len(mgr._active) == 2  # one was evicted


# ---- RedisDistributor tests ---------------------------------------------------


@pytest.fixture
def fake_redis():
    """Create a fakeredis instance for testing."""
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.mark.asyncio
async def test_distributor_publish_quote(fake_redis):
    distributor = RedisDistributor(redis_client=fake_redis)
    snapshot = QuoteSnapshot(
        symbol="SPY",
        con_id=12345,
        sec_type="STK",
        bid=450.10,
        ask=450.15,
        last=450.12,
    )
    await distributor.publish_quote(snapshot)
    # Verify HSET was written
    data = await fake_redis.hgetall("mktdata:latest:quote:SPY")
    assert data  # non-empty
    assert "symbol" in data or "bid" in data  # some fields exist


@pytest.mark.asyncio
async def test_distributor_publish_greeks(fake_redis):
    distributor = RedisDistributor(redis_client=fake_redis)
    snapshot = GreeksSnapshot(
        symbol="AAPL",
        con_id=99999,
        implied_vol=0.25,
        delta=0.45,
        gamma=0.02,
        theta=-0.05,
        vega=0.15,
        und_price=150.0,
    )
    await distributor.publish_greeks(snapshot)
    # Verify HSET was written
    data = await fake_redis.hgetall("mktdata:latest:greeks:99999")
    assert data  # non-empty


@pytest.mark.asyncio
async def test_distributor_error_handling():
    """Redis errors must not propagate (non-fatal)."""
    bad_redis = AsyncMock()
    bad_redis.publish = AsyncMock(side_effect=Exception("Redis connection error"))
    bad_redis.hset = AsyncMock(side_effect=Exception("Redis connection error"))

    distributor = RedisDistributor(redis_client=bad_redis)
    snapshot = QuoteSnapshot(symbol="SPY", con_id=12345, sec_type="STK")

    # Must not raise even when Redis fails
    await distributor.publish_quote(snapshot)  # no exception


@pytest.mark.asyncio
async def test_distributor_get_latest_quote(fake_redis):
    """get_latest_quote returns None for missing symbol, data for existing."""
    distributor = RedisDistributor(redis_client=fake_redis)

    # No data yet
    result = await distributor.get_latest_quote("MISSING")
    assert result is None

    # Publish then retrieve
    snapshot = QuoteSnapshot(
        symbol="TSLA",
        con_id=55555,
        sec_type="STK",
        bid=200.0,
        ask=200.10,
    )
    await distributor.publish_quote(snapshot)
    result = await distributor.get_latest_quote("TSLA")
    assert result is not None
    assert "TSLA" in str(result)
