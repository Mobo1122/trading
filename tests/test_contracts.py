"""Unit tests for ContractCache and ContractResolver.

Tests use fakeredis for Redis and mock IB API calls. No live IB Gateway
or Redis server is required.

Tests verify:
  - Cache miss/hit/invalidation behavior
  - JSON serialization round-trip for chain data
  - Cache-through pattern (miss -> IB fetch -> cache populate)
  - Option chain retrieval for STK and IND underlyings
  - Contract qualification filtering
  - Error handling for invalid underlyings
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest
from ib_async import Index, Option, Stock
from ib_async.objects import OptionChain

from trading.contracts.cache import ContractCache
from trading.contracts.resolver import ContractResolver


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_redis():
    """Create a fakeredis async client with decode_responses=True."""
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def cache(fake_redis):
    """Create a ContractCache backed by fakeredis."""
    return ContractCache(redis_client=fake_redis, ttl=300)


@pytest.fixture
def sample_chain_data():
    """Realistic option chain data dict."""
    return {
        "symbol": "AAPL",
        "exchange": "SMART",
        "trading_class": "AAPL",
        "multiplier": "100",
        "expirations": ["20260401", "20260408", "20260415"],
        "strikes": [140.0, 145.0, 150.0, 155.0, 160.0],
    }


@pytest.fixture
def mock_ib():
    """Create a mock IB instance with async methods."""
    ib = MagicMock()
    ib.qualifyContractsAsync = AsyncMock()
    ib.reqSecDefOptParamsAsync = AsyncMock()
    return ib


@pytest.fixture
def resolver(mock_ib, cache):
    """Create a ContractResolver with mock IB and real cache."""
    return ContractResolver(ib=mock_ib, cache=cache)


def _make_qualified_stock(symbol: str = "AAPL", con_id: int = 265598) -> Stock:
    """Create a Stock that looks like it was qualified by IB."""
    stock = Stock(symbol, "SMART", "USD")
    stock.conId = con_id
    return stock


def _make_qualified_index(symbol: str = "SPX", con_id: int = 416904) -> Index:
    """Create an Index that looks like it was qualified by IB."""
    idx = Index(symbol, "CBOE", "USD")
    idx.conId = con_id
    return idx


def _make_option_chain(
    exchange: str = "SMART",
    trading_class: str = "AAPL",
    multiplier: str = "100",
    underlying_con_id: int = 265598,
) -> OptionChain:
    """Create a realistic OptionChain as returned by reqSecDefOptParamsAsync."""
    return OptionChain(
        exchange=exchange,
        underlyingConId=underlying_con_id,
        tradingClass=trading_class,
        multiplier=multiplier,
        expirations=["20260401", "20260408", "20260415"],
        strikes=[140.0, 145.0, 150.0, 155.0, 160.0],
    )


# ---------------------------------------------------------------------------
# ContractCache tests
# ---------------------------------------------------------------------------


class TestContractCacheMiss:
    """Test cache miss behavior."""

    async def test_cache_miss_returns_none(self, cache):
        """Empty cache returns None for any symbol."""
        result = await cache.get_chain("AAPL")
        assert result is None

    async def test_contract_cache_miss_returns_none(self, cache):
        """Empty cache returns None for any contract ID."""
        result = await cache.get_qualified_contract(265598)
        assert result is None


class TestContractCacheSetAndGet:
    """Test cache set/get round-trip."""

    async def test_cache_set_and_get(self, cache, sample_chain_data):
        """Set chain data, get it back, verify it matches."""
        await cache.set_chain("AAPL", sample_chain_data)
        result = await cache.get_chain("AAPL")

        assert result is not None
        assert result["symbol"] == "AAPL"
        assert result["exchange"] == "SMART"
        assert result["trading_class"] == "AAPL"
        assert result["multiplier"] == "100"
        assert result["expirations"] == ["20260401", "20260408", "20260415"]
        assert result["strikes"] == [140.0, 145.0, 150.0, 155.0, 160.0]

    async def test_contract_set_and_get(self, cache):
        """Set a qualified contract, get it back."""
        contract_data = {
            "conId": 265598,
            "symbol": "AAPL",
            "secType": "STK",
            "exchange": "SMART",
        }
        await cache.set_qualified_contract(265598, contract_data)
        result = await cache.get_qualified_contract(265598)

        assert result is not None
        assert result["conId"] == 265598
        assert result["symbol"] == "AAPL"


class TestContractCacheInvalidate:
    """Test cache invalidation."""

    async def test_cache_invalidate(self, cache, sample_chain_data):
        """Set data, invalidate, verify returns None."""
        await cache.set_chain("AAPL", sample_chain_data)
        assert await cache.get_chain("AAPL") is not None

        await cache.invalidate_chain("AAPL")
        assert await cache.get_chain("AAPL") is None


class TestContractCacheSerialization:
    """Test serialization edge cases."""

    async def test_cache_serialization_preserves_types(self, cache):
        """Chain data with various numeric types round-trips correctly."""
        chain_data = {
            "symbol": "TSLA",
            "exchange": "SMART",
            "trading_class": "TSLA",
            "multiplier": "100",
            "expirations": ["20260401", "20260501"],
            "strikes": [200.0, 205.5, 210.0, 215.0],
        }
        await cache.set_chain("TSLA", chain_data)
        result = await cache.get_chain("TSLA")

        assert isinstance(result["expirations"], list)
        assert isinstance(result["strikes"], list)
        assert result["strikes"] == [200.0, 205.5, 210.0, 215.0]
        assert all(isinstance(s, float) for s in result["strikes"])

    async def test_cache_handles_empty_lists(self, cache):
        """Chain data with empty expirations/strikes round-trips."""
        chain_data = {
            "symbol": "XYZ",
            "exchange": "SMART",
            "trading_class": "XYZ",
            "multiplier": "100",
            "expirations": [],
            "strikes": [],
        }
        await cache.set_chain("XYZ", chain_data)
        result = await cache.get_chain("XYZ")

        assert result["expirations"] == []
        assert result["strikes"] == []


# ---------------------------------------------------------------------------
# ContractResolver tests
# ---------------------------------------------------------------------------


class TestGetOptionChainCacheHit:
    """Test cache hit path - IB API should NOT be called."""

    async def test_get_option_chain_cache_hit(
        self, resolver, cache, mock_ib, sample_chain_data
    ):
        """When cache has data, IB API is not called."""
        # Pre-populate cache
        await cache.set_chain("AAPL", sample_chain_data)

        result = await resolver.get_option_chain("AAPL")

        assert result["symbol"] == "AAPL"
        assert result["expirations"] == ["20260401", "20260408", "20260415"]
        # IB API should NOT have been called
        mock_ib.qualifyContractsAsync.assert_not_called()
        mock_ib.reqSecDefOptParamsAsync.assert_not_called()


class TestGetOptionChainCacheMiss:
    """Test cache miss path - IB API called, cache populated."""

    async def test_get_option_chain_cache_miss(
        self, resolver, cache, mock_ib
    ):
        """On cache miss, fetches from IB and populates cache."""
        qualified_stock = _make_qualified_stock()
        mock_ib.qualifyContractsAsync.return_value = [qualified_stock]
        mock_ib.reqSecDefOptParamsAsync.return_value = [
            _make_option_chain()
        ]

        result = await resolver.get_option_chain("AAPL")

        # Verify IB API was called
        mock_ib.qualifyContractsAsync.assert_called_once()
        mock_ib.reqSecDefOptParamsAsync.assert_called_once()

        # Verify result
        assert result["symbol"] == "AAPL"
        assert result["exchange"] == "SMART"
        assert "20260401" in result["expirations"]
        assert 150.0 in result["strikes"]

        # Verify cache was populated
        cached = await cache.get_chain("AAPL")
        assert cached is not None
        assert cached["symbol"] == "AAPL"


class TestGetOptionChainStock:
    """Test STK underlying type creates Stock contract."""

    async def test_get_option_chain_stock(self, resolver, mock_ib):
        """STK sec_type creates a Stock underlying."""
        qualified_stock = _make_qualified_stock()
        mock_ib.qualifyContractsAsync.return_value = [qualified_stock]
        mock_ib.reqSecDefOptParamsAsync.return_value = [
            _make_option_chain()
        ]

        await resolver.get_option_chain("AAPL", sec_type="STK")

        # Check that qualifyContractsAsync was called with a Stock
        call_args = mock_ib.qualifyContractsAsync.call_args
        contract = call_args[0][0]
        assert isinstance(contract, Stock)
        assert contract.symbol == "AAPL"


class TestGetOptionChainIndex:
    """Test IND underlying type creates Index contract."""

    async def test_get_option_chain_index(self, resolver, mock_ib):
        """IND sec_type creates an Index underlying."""
        qualified_index = _make_qualified_index()
        mock_ib.qualifyContractsAsync.return_value = [qualified_index]
        mock_ib.reqSecDefOptParamsAsync.return_value = [
            _make_option_chain(
                exchange="CBOE",
                trading_class="SPX",
                underlying_con_id=416904,
            )
        ]

        await resolver.get_option_chain("SPX", sec_type="IND", exchange="CBOE")

        call_args = mock_ib.qualifyContractsAsync.call_args
        contract = call_args[0][0]
        assert isinstance(contract, Index)
        assert contract.symbol == "SPX"


class TestQualifyOptions:
    """Test option contract qualification."""

    async def test_qualify_options_filters_none(self, resolver, mock_ib):
        """Contracts that can't be qualified (None or conId=0) are filtered out."""
        # Build two valid options and one invalid
        valid_opt1 = Option("AAPL", "20260401", 150.0, "C", "SMART")
        valid_opt1.conId = 100001

        valid_opt2 = Option("AAPL", "20260401", 150.0, "P", "SMART")
        valid_opt2.conId = 100002

        invalid_opt = Option("AAPL", "20260401", 155.0, "C", "SMART")
        invalid_opt.conId = 0  # Not qualified

        mock_ib.qualifyContractsAsync.return_value = [
            valid_opt1,
            valid_opt2,
            invalid_opt,
            None,  # Completely failed
        ]

        result = await resolver.qualify_options(
            "AAPL",
            expirations=["20260401"],
            strikes=[150.0, 155.0],
            rights=["C", "P"],
        )

        # Only the two valid options should be returned
        assert len(result) == 2
        assert all(c.conId > 0 for c in result)

    async def test_qualify_options_empty_input(self, resolver, mock_ib):
        """Empty expirations/strikes returns empty list without API call."""
        result = await resolver.qualify_options(
            "AAPL",
            expirations=[],
            strikes=[150.0],
        )
        assert result == []
        mock_ib.qualifyContractsAsync.assert_not_called()


class TestInvalidUnderlying:
    """Test error handling for unqualifiable underlyings."""

    async def test_invalid_underlying_raises_value_error(
        self, resolver, mock_ib
    ):
        """ValueError raised when underlying can't be qualified."""
        # qualifyContractsAsync returns empty list
        mock_ib.qualifyContractsAsync.return_value = []

        with pytest.raises(ValueError, match="Cannot qualify underlying"):
            await resolver.get_option_chain("INVALID_SYMBOL")

    async def test_unknown_sec_type_raises_value_error(self, resolver):
        """ValueError raised for unknown security type."""
        with pytest.raises(ValueError, match="Unknown security type"):
            await resolver.get_underlying("AAPL", sec_type="BOND")

    async def test_no_chains_raises_value_error(self, resolver, mock_ib):
        """ValueError raised when IB returns no chains."""
        qualified_stock = _make_qualified_stock()
        mock_ib.qualifyContractsAsync.return_value = [qualified_stock]
        mock_ib.reqSecDefOptParamsAsync.return_value = []  # No chains

        with pytest.raises(ValueError, match="No option chains found"):
            await resolver.get_option_chain("AAPL")


class TestGetOptionChainNoCache:
    """Test use_cache=False bypasses cache."""

    async def test_use_cache_false_bypasses_cache(
        self, resolver, cache, mock_ib, sample_chain_data
    ):
        """use_cache=False fetches from IB even if cache has data."""
        # Pre-populate cache
        await cache.set_chain("AAPL", sample_chain_data)

        qualified_stock = _make_qualified_stock()
        mock_ib.qualifyContractsAsync.return_value = [qualified_stock]
        mock_ib.reqSecDefOptParamsAsync.return_value = [
            _make_option_chain()
        ]

        result = await resolver.get_option_chain("AAPL", use_cache=False)

        # IB API should have been called despite cache having data
        mock_ib.qualifyContractsAsync.assert_called_once()
        mock_ib.reqSecDefOptParamsAsync.assert_called_once()
        assert result["symbol"] == "AAPL"
