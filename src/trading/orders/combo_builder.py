"""BAG contract construction for multi-leg spread orders.

Provides ComboOrderBuilder, a stateless utility class that constructs
IB BAG contracts with ComboLeg objects for vertical spreads, iron condors,
butterflies, and other multi-leg options strategies (up to 6 legs).
"""

from __future__ import annotations

import structlog
from ib_async import Bag, ComboLeg, TagValue

from trading.risk.models import TradeLeg

logger = structlog.get_logger(__name__)


class ComboOrderBuilder:
    """Constructs IB BAG contracts for multi-leg spread orders.

    All methods are static since the builder is a stateless utility.
    Validates leg count (1-6 per IB maximum) and contract qualification.
    """

    MAX_LEGS = 6  # IB maximum

    @staticmethod
    def build_bag(
        symbol: str,
        legs: list[dict],
        exchange: str = "SMART",
        currency: str = "USD",
    ) -> Bag:
        """Build a Bag contract from leg specifications.

        Each leg dict must have: conId (int), ratio (int), action ("BUY"/"SELL").
        Validates leg count <= 6 (IB maximum).

        Args:
            symbol: Underlying symbol (e.g. "AAPL", "SPY").
            legs: List of dicts with keys: conId, ratio, action.
            exchange: Exchange routing (default "SMART").
            currency: Currency code (default "USD").

        Returns:
            Configured Bag contract with ComboLegs.

        Raises:
            ValueError: If legs is empty or exceeds MAX_LEGS.
        """
        if not legs:
            raise ValueError("At least one leg required")
        if len(legs) > ComboOrderBuilder.MAX_LEGS:
            raise ValueError(
                f"Maximum {ComboOrderBuilder.MAX_LEGS} legs allowed, "
                f"got {len(legs)}"
            )

        bag = Bag(symbol=symbol, exchange=exchange, currency=currency)
        bag.comboLegs = [
            ComboLeg(
                conId=leg["conId"],
                ratio=leg["ratio"],
                action=leg["action"],
                exchange=exchange,
            )
            for leg in legs
        ]

        logger.debug(
            "built_bag_contract",
            symbol=symbol,
            num_legs=len(legs),
            exchange=exchange,
        )

        return bag

    @staticmethod
    def build_from_trade_legs(
        symbol: str,
        trade_legs: list[TradeLeg],
        exchange: str = "SMART",
        currency: str = "USD",
    ) -> Bag:
        """Build a Bag contract from TradeProposal TradeLeg objects.

        Each TradeLeg must have a qualified contract (with conId set).
        Raises ValueError if any leg lacks a qualified contract.

        Args:
            symbol: Underlying symbol (e.g. "AAPL", "SPY").
            trade_legs: List of TradeLeg objects from a TradeProposal.
            exchange: Exchange routing (default "SMART").
            currency: Currency code (default "USD").

        Returns:
            Configured Bag contract with ComboLegs.

        Raises:
            ValueError: If trade_legs is empty, exceeds MAX_LEGS,
                or any leg lacks a qualified contract.
        """
        if not trade_legs:
            raise ValueError("At least one leg required")
        if len(trade_legs) > ComboOrderBuilder.MAX_LEGS:
            raise ValueError(
                f"Maximum {ComboOrderBuilder.MAX_LEGS} legs, "
                f"got {len(trade_legs)}"
            )

        for leg in trade_legs:
            if leg.contract is None or leg.contract.conId == 0:
                raise ValueError(
                    f"Leg for {leg.symbol} missing qualified contract "
                    f"(conId=0)"
                )

        bag = Bag(symbol=symbol, exchange=exchange, currency=currency)
        bag.comboLegs = [
            ComboLeg(
                conId=leg.contract.conId,
                ratio=leg.quantity,
                action=leg.action,
                exchange=exchange,
            )
            for leg in trade_legs
        ]

        logger.debug(
            "built_bag_from_trade_legs",
            symbol=symbol,
            num_legs=len(trade_legs),
            exchange=exchange,
        )

        return bag

    @staticmethod
    def apply_combo_routing(order) -> None:
        """Add NonGuaranteed routing params to a combo order.

        Required for SMART-routed combo orders per IB API docs.
        Modifies the order object in-place.

        Args:
            order: An ib_async Order object (MarketOrder, LimitOrder, etc.).
        """
        order.smartComboRoutingParams = [TagValue("NonGuaranteed", "1")]
        logger.debug("applied_combo_routing", order_type=type(order).__name__)
