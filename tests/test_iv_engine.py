"""Tests for IV rank/percentile computation in IVEngine.

Covers static computation methods (rank, percentile), edge cases
(insufficient data, no range, clamping), and cache invalidation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from trading.analytics.iv_engine import IVEngine
from trading.market_data.models import IVData


# Build a consistent history list for testing (25 values from 0.10 to 0.34)
HISTORY_25 = [round(0.10 + i * 0.01, 2) for i in range(25)]  # 0.10 to 0.34


# ---- IV rank tests -----------------------------------------------------------


def test_iv_rank_basic():
    # current_iv = 0.22, low = 0.10, high = 0.34 => (0.22-0.10)/(0.34-0.10)*100 = 50.0
    rank = IVEngine.calculate_iv_rank(0.22, HISTORY_25)
    assert rank is not None
    assert abs(rank - 50.0) < 0.1


def test_iv_rank_at_high():
    rank = IVEngine.calculate_iv_rank(0.34, HISTORY_25)
    assert rank == 100.0


def test_iv_rank_at_low():
    rank = IVEngine.calculate_iv_rank(0.10, HISTORY_25)
    assert rank == 0.0


def test_iv_rank_above_high_clamped():
    rank = IVEngine.calculate_iv_rank(0.99, HISTORY_25)
    assert rank == 100.0


def test_iv_rank_below_low_clamped():
    rank = IVEngine.calculate_iv_rank(0.01, HISTORY_25)
    assert rank == 0.0


def test_iv_rank_insufficient_data_returns_none():
    assert IVEngine.calculate_iv_rank(0.25, []) is None
    assert IVEngine.calculate_iv_rank(0.25, [0.2, 0.3]) is None
    assert IVEngine.calculate_iv_rank(0.25, [0.2] * 19) is None  # exactly 19


def test_iv_rank_exactly_20_returns_value():
    history = [0.2] * 19 + [0.3]  # 20 values
    rank = IVEngine.calculate_iv_rank(0.25, history)
    assert rank is not None


def test_iv_rank_no_range_returns_50():
    # All same value -> no range
    history = [0.25] * 25
    rank = IVEngine.calculate_iv_rank(0.25, history)
    assert rank == 50.0


# ---- IV percentile tests -----------------------------------------------------


def test_iv_percentile_basic():
    # current_iv = 0.22: 12 values below (0.10..0.21), 25 total => 12/25*100 = 48.0
    pct = IVEngine.calculate_iv_percentile(0.22, HISTORY_25)
    assert pct is not None
    assert abs(pct - 48.0) < 0.1


def test_iv_percentile_at_minimum():
    # 0.10 is the minimum in HISTORY_25 -- nothing below it
    pct = IVEngine.calculate_iv_percentile(0.10, HISTORY_25)
    assert pct == 0.0


def test_iv_percentile_at_maximum():
    # Above all history values
    pct = IVEngine.calculate_iv_percentile(0.99, HISTORY_25)
    assert pct == 100.0


def test_iv_percentile_insufficient_data_returns_none():
    assert IVEngine.calculate_iv_percentile(0.25, []) is None
    assert IVEngine.calculate_iv_percentile(0.25, [0.2] * 5) is None


def test_iv_percentile_exactly_20_returns_value():
    history = [0.15 + i * 0.01 for i in range(20)]
    pct = IVEngine.calculate_iv_percentile(0.25, history)
    assert pct is not None


# ---- Cache invalidation tests -------------------------------------------------


def test_iv_engine_cache_invalidation_single():
    """invalidate_cache(symbol) removes only that symbol."""
    iv_history = MagicMock()
    settings = MagicMock()
    settings.market_data.iv_refresh_interval_minutes = 15
    engine = IVEngine(iv_history=iv_history, settings=settings)

    # Populate cache manually
    engine._cache["SPY"] = IVData(
        symbol="SPY", data_points=100, computed_at=datetime.now(timezone.utc)
    )
    engine._cache_timestamps["SPY"] = 0.0
    engine._cache["AAPL"] = IVData(
        symbol="AAPL", data_points=50, computed_at=datetime.now(timezone.utc)
    )
    engine._cache_timestamps["AAPL"] = 0.0

    engine.invalidate_cache("SPY")
    assert "SPY" not in engine._cache
    assert "AAPL" in engine._cache  # other symbol untouched


def test_iv_engine_cache_invalidation_all():
    """invalidate_cache() with no args clears all entries."""
    iv_history = MagicMock()
    settings = MagicMock()
    settings.market_data.iv_refresh_interval_minutes = 15
    engine = IVEngine(iv_history=iv_history, settings=settings)

    engine._cache["SPY"] = IVData(
        symbol="SPY", data_points=100, computed_at=datetime.now(timezone.utc)
    )
    engine._cache_timestamps["SPY"] = 0.0
    engine._cache["AAPL"] = IVData(
        symbol="AAPL", data_points=50, computed_at=datetime.now(timezone.utc)
    )
    engine._cache_timestamps["AAPL"] = 0.0

    engine.invalidate_cache()  # clear all
    assert len(engine._cache) == 0
    assert len(engine._cache_timestamps) == 0


def test_iv_engine_get_cached_returns_none_for_missing():
    """get_cached returns None for symbols not in cache."""
    iv_history = MagicMock()
    settings = MagicMock()
    settings.market_data.iv_refresh_interval_minutes = 15
    engine = IVEngine(iv_history=iv_history, settings=settings)

    assert engine.get_cached("MISSING") is None


def test_iv_engine_get_cached_returns_data():
    """get_cached returns IVData for cached symbols."""
    iv_history = MagicMock()
    settings = MagicMock()
    settings.market_data.iv_refresh_interval_minutes = 15
    engine = IVEngine(iv_history=iv_history, settings=settings)

    iv_data = IVData(
        symbol="SPY", data_points=100, computed_at=datetime.now(timezone.utc)
    )
    engine._cache["SPY"] = iv_data

    result = engine.get_cached("SPY")
    assert result is not None
    assert result.symbol == "SPY"
    assert result.data_points == 100
