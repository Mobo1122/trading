"""Unit tests for the EarningsCalendar service.

Tests cover:
- EarningsFlag Pydantic model creation and serialization
- EarningsCalendar.needs_refresh cache staleness logic
- Graceful handling of missing Finnhub API key
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from trading.analytics.earnings import EarningsCalendar
from trading.market_data.models import EarningsFlag


@pytest.fixture
def mock_settings():
    """Provide mock settings with empty API key and default lookout days."""
    settings = MagicMock()
    settings.market_data.finnhub_api_key = ""
    settings.market_data.earnings_lookout_days = 7
    return settings


@pytest.fixture
def mock_session_factory():
    """Provide a mock async session factory."""
    return AsyncMock()


@pytest.fixture
def calendar(mock_session_factory, mock_settings):
    """Provide an EarningsCalendar with mocked dependencies."""
    return EarningsCalendar(mock_session_factory, mock_settings)


def test_earnings_flag_model_creation():
    """EarningsFlag stores all fields correctly."""
    flag = EarningsFlag(
        symbol="AAPL",
        earnings_date=date.today() + timedelta(days=5),
        days_until=5,
        hour="amc",
        eps_estimate=1.65,
        revenue_estimate=94200000000,
        fetched_at=datetime.now(),
    )
    assert flag.symbol == "AAPL"
    assert flag.days_until == 5
    assert flag.hour == "amc"
    assert flag.eps_estimate == 1.65
    assert flag.revenue_estimate == 94200000000


def test_earnings_flag_optional_fields():
    """EarningsFlag works with only required fields."""
    flag = EarningsFlag(
        symbol="TSLA",
        earnings_date=date.today() + timedelta(days=2),
        days_until=2,
        fetched_at=datetime.now(),
    )
    assert flag.symbol == "TSLA"
    assert flag.hour is None
    assert flag.eps_estimate is None
    assert flag.revenue_estimate is None


def test_earnings_flag_serialization():
    """EarningsFlag serializes to JSON with all expected fields."""
    flag = EarningsFlag(
        symbol="MSFT",
        earnings_date=date.today() + timedelta(days=3),
        days_until=3,
        hour="bmo",
        fetched_at=datetime.now(),
    )
    json_str = flag.model_dump_json()
    assert "MSFT" in json_str
    assert "bmo" in json_str
    assert "days_until" in json_str


def test_needs_refresh_no_prior_refresh(calendar):
    """needs_refresh returns True when no refresh has occurred."""
    assert calendar.needs_refresh() is True


def test_needs_refresh_stale(calendar):
    """needs_refresh returns True when last refresh was over 24 hours ago."""
    calendar._last_refresh = time.time() - (25 * 3600)
    assert calendar.needs_refresh() is True


def test_needs_refresh_fresh(calendar):
    """needs_refresh returns False when last refresh was recent."""
    calendar._last_refresh = time.time() - 3600
    assert calendar.needs_refresh() is False


def test_needs_refresh_boundary(calendar):
    """needs_refresh returns True at exactly 24 hours."""
    calendar._last_refresh = time.time() - 86400 - 1
    assert calendar.needs_refresh() is True


async def test_fetch_earnings_no_api_key(calendar):
    """fetch_earnings returns empty list when API key is not configured."""
    result = await calendar.fetch_earnings(
        "AAPL", date.today(), date.today() + timedelta(days=30)
    )
    assert result == []


async def test_fetch_earnings_no_api_key_no_crash(calendar):
    """fetch_earnings does not raise when API key is missing."""
    # Should not raise any exception
    result = await calendar.fetch_earnings(
        "MSFT", date.today(), date.today() + timedelta(days=7)
    )
    assert isinstance(result, list)
    assert len(result) == 0
