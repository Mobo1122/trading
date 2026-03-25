"""Option chain retrieval and contract qualification via IB API.

This module is the core interface between the trading system and IB's
contract/chain data. It uses reqSecDefOptParamsAsync (NOT reqContractDetails,
which is heavily throttled) to retrieve complete option chains for any
underlying, and qualifyContractsAsync to validate individual contracts.

Key design:
  - Cache-through pattern: check Redis first, fetch from IB on miss
  - Supports STK (equities/ETFs), IND (indices), FUT (futures) underlyings
  - Graceful error handling with clear ValueError messages
  - Cache failures never block the critical path
"""

from __future__ import annotations

import structlog
from ib_async import IB, Future, Index, Option, Stock

from trading.contracts.cache import ContractCache

logger = structlog.get_logger()


class ContractResolver:
    """Retrieves option chains and qualifies contracts via IB API.

    Uses a cache-through pattern: on get_option_chain(), checks Redis
    first. On cache miss, fetches from IB via reqSecDefOptParamsAsync
    and populates the cache before returning.

    Args:
        ib: Connected IB instance (from ib_async).
        cache: ContractCache for Redis-backed caching.
    """

    def __init__(self, ib: IB, cache: ContractCache) -> None:
        self.ib = ib
        self.cache = cache
        self._log = logger.bind(component="contract_resolver")

    async def get_option_chain(
        self,
        symbol: str,
        sec_type: str = "STK",
        exchange: str = "SMART",
        use_cache: bool = True,
    ) -> dict:
        """Retrieve complete option chain for an underlying.

        Returns all available expirations and strikes for the symbol.
        Uses reqSecDefOptParamsAsync which is not rate-limited like
        reqContractDetails.

        Args:
            symbol: Underlying symbol (e.g., "AAPL", "SPX").
            sec_type: Security type - "STK" for stocks/ETFs, "IND" for
                indices, "FUT" for futures.
            exchange: Exchange to filter chains on. Default "SMART".
            use_cache: Whether to check cache first. Set False to force
                fresh data from IB.

        Returns:
            Dict with keys: symbol, exchange, trading_class, multiplier,
            expirations (sorted list of YYYYMMDD strings),
            strikes (sorted list of floats).

        Raises:
            ValueError: If underlying cannot be qualified or no chains found.
        """
        # 1. Check cache
        if use_cache:
            cached = await self.cache.get_chain(symbol)
            if cached is not None:
                self._log.debug("chain.cache_hit", symbol=symbol)
                return cached

        # 2. Cache miss - fetch from IB
        self._log.info("chain.fetching", symbol=symbol, sec_type=sec_type)

        # 2a. Qualify the underlying contract
        underlying = await self.get_underlying(symbol, sec_type)

        # 2b. Request option chain parameters
        chains = await self.ib.reqSecDefOptParamsAsync(
            underlyingSymbol=underlying.symbol,
            futFopExchange="",
            underlyingSecType=sec_type,
            underlyingConId=underlying.conId,
        )

        if not chains:
            raise ValueError(f"No option chains found for {symbol}")

        # 2c. Filter to matching exchange and trading class
        # Prefer SMART exchange, fall back to first available
        matching = [c for c in chains if c.exchange == exchange]
        if not matching:
            # If no exact exchange match, use all chains
            matching = chains

        # Pick the chain with the matching trading class (usually == symbol)
        chain = matching[0]
        for c in matching:
            if c.tradingClass == symbol:
                chain = c
                break

        # 2d. Convert to serializable dict
        # Handle both list and frozenset (ib_async version compatibility)
        expirations = sorted(list(chain.expirations))
        strikes = sorted(list(chain.strikes))

        chain_data = {
            "symbol": symbol,
            "exchange": chain.exchange,
            "trading_class": chain.tradingClass,
            "multiplier": chain.multiplier,
            "expirations": expirations,
            "strikes": strikes,
        }

        # 3. Store in cache (failures are non-fatal)
        await self.cache.set_chain(symbol, chain_data)

        self._log.info(
            "chain.fetched",
            symbol=symbol,
            expirations=len(expirations),
            strikes=len(strikes),
        )

        return chain_data

    async def qualify_options(
        self,
        symbol: str,
        expirations: list[str],
        strikes: list[float],
        rights: list[str] | None = None,
        exchange: str = "SMART",
    ) -> list[Option]:
        """Qualify (validate) option contracts for given parameters.

        Builds Option contract objects for all combinations of
        expiration/strike/right and qualifies them via IB. Contracts
        that cannot be qualified are filtered out.

        Args:
            symbol: Underlying symbol.
            expirations: List of expiration dates (YYYYMMDD format).
            strikes: List of strike prices.
            rights: List of option rights ("C" for call, "P" for put).
                Defaults to both ["C", "P"].
            exchange: Exchange. Default "SMART".

        Returns:
            List of qualified Option contract objects. Unqualified
            contracts (IB returned None/empty) are excluded.
        """
        if rights is None:
            rights = ["C", "P"]

        contracts = []
        for exp in expirations:
            for strike in strikes:
                for right in rights:
                    contracts.append(
                        Option(
                            symbol=symbol,
                            lastTradeDateOrContractMonth=exp,
                            strike=strike,
                            right=right,
                            exchange=exchange,
                        )
                    )

        if not contracts:
            return []

        self._log.info(
            "options.qualifying",
            symbol=symbol,
            count=len(contracts),
        )

        qualified = await self.ib.qualifyContractsAsync(*contracts)

        # Filter out None entries (contracts that couldn't be qualified)
        result = [c for c in qualified if c is not None and c.conId > 0]

        self._log.info(
            "options.qualified",
            symbol=symbol,
            requested=len(contracts),
            qualified=len(result),
        )

        return result

    async def get_underlying(
        self,
        symbol: str,
        sec_type: str = "STK",
    ) -> Stock | Index | Future:
        """Create and qualify an underlying contract.

        Args:
            symbol: The symbol (e.g., "AAPL", "SPX", "ES").
            sec_type: Security type - "STK", "IND", or "FUT".

        Returns:
            Qualified contract object (Stock, Index, or Future).

        Raises:
            ValueError: If security type is unknown or contract cannot
                be qualified by IB.
        """
        if sec_type == "STK":
            contract = Stock(symbol, "SMART", "USD")
        elif sec_type == "IND":
            contract = Index(symbol, "CBOE", "USD")
        elif sec_type == "FUT":
            contract = Future(symbol, exchange="CME", currency="USD")
        else:
            raise ValueError(
                f"Unknown security type: {sec_type}. "
                f"Supported: STK, IND, FUT"
            )

        qualified = await self.ib.qualifyContractsAsync(contract)

        if not qualified or qualified[0] is None or qualified[0].conId == 0:
            raise ValueError(
                f"Cannot qualify underlying: {symbol} ({sec_type})"
            )

        return qualified[0]
