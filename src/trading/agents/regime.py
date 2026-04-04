"""Deterministic market regime detection module.

Classifies current market conditions from quantitative indicators (IV rank
average, price momentum) and maps each regime to a strategy weight
distribution. This is intentionally NOT machine-learning-based -- deterministic
logic ensures testability, explainability, and auditability for a real-money
trading system.

The regime detector maintains hysteresis state to prevent "regime whiplash"
where rapid oscillation between regimes would cause the scanner to flip
strategies on every pipeline run.

Pipeline integration:
    The scanner agent calls ``RegimeDetector.detect()`` at the start of each
    pipeline run. The resulting ``RegimeClassification`` is serialized into
    ``PipelineState.regime_classification`` and used by downstream agents
    to adapt strategy selection via ``REGIME_STRATEGY_WEIGHTS``.
"""

from __future__ import annotations

from enum import Enum

import structlog
from pydantic import BaseModel, Field

from trading.agents.config import RegimeConfig
from trading.market_data.models import IVData

logger = structlog.get_logger(component="regime_detector")


# ---------------------------------------------------------------------------
# MarketRegime enum
# ---------------------------------------------------------------------------


class MarketRegime(str, Enum):
    """Market regime classifications.

    Six mutually-exclusive regimes derived from trend (bullish/bearish/neutral)
    and volatility (high/low/normal) signals. UNKNOWN is the safe default
    when insufficient data is available.
    """

    BULL_QUIET = "bull_quiet"
    BULL_VOLATILE = "bull_volatile"
    BEAR_QUIET = "bear_quiet"
    BEAR_VOLATILE = "bear_volatile"
    SIDEWAYS = "sideways"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# RegimeClassification model
# ---------------------------------------------------------------------------


class RegimeClassification(BaseModel):
    """Result of a regime detection run.

    Contains the classified regime, confidence score, raw indicator values
    for audit trail, and human-readable reasoning. Serialized into
    ``PipelineState.regime_classification`` via ``model_dump()``.
    """

    regime: MarketRegime
    confidence: float = Field(ge=0, le=1)
    trend_signal: str
    volatility_signal: str
    indicators: dict
    reasoning: str
    previous_regime: MarketRegime | None = None


# ---------------------------------------------------------------------------
# Strategy weight distributions per regime
# ---------------------------------------------------------------------------

REGIME_STRATEGY_WEIGHTS: dict[MarketRegime, dict[str, float]] = {
    MarketRegime.BULL_QUIET: {
        "covered_call": 0.3,
        "cash_secured_put": 0.3,
        "vertical_spread": 0.2,
        "iron_condor": 0.2,
    },
    MarketRegime.BULL_VOLATILE: {
        "covered_call": 0.3,
        "vertical_spread": 0.3,
        "iron_condor": 0.2,
        "cash_secured_put": 0.2,
    },
    MarketRegime.BEAR_QUIET: {
        "covered_call": 0.4,
        "vertical_spread": 0.3,
        "iron_condor": 0.2,
        "cash_secured_put": 0.1,
    },
    MarketRegime.BEAR_VOLATILE: {
        "covered_call": 0.5,
        "vertical_spread": 0.4,
        "iron_condor": 0.1,
        "cash_secured_put": 0.0,
    },
    MarketRegime.SIDEWAYS: {
        "iron_condor": 0.4,
        "covered_call": 0.2,
        "cash_secured_put": 0.2,
        "calendar_spread": 0.2,
    },
    MarketRegime.UNKNOWN: {
        "covered_call": 0.25,
        "cash_secured_put": 0.25,
        "vertical_spread": 0.25,
        "iron_condor": 0.25,
    },
}


# ---------------------------------------------------------------------------
# RegimeDetector
# ---------------------------------------------------------------------------


class RegimeDetector:
    """Deterministic market regime classifier.

    Computes market regime from IV rank averages and price momentum,
    with hysteresis to prevent regime whiplash. Each regime maps to
    a strategy weight distribution via ``REGIME_STRATEGY_WEIGHTS``.

    Args:
        config: Regime detection thresholds and hysteresis settings.

    Usage::

        detector = RegimeDetector(config)
        classification = await detector.detect(iv_data, price_data)
        weights = detector.get_strategy_weights(classification.regime)
    """

    def __init__(self, config: RegimeConfig) -> None:
        self._config = config
        self._consecutive_count: int = 0
        self._pending_regime: MarketRegime | None = None
        self._current_regime: MarketRegime = MarketRegime.UNKNOWN

    @property
    def current_regime(self) -> MarketRegime:
        """Return the current confirmed regime."""
        return self._current_regime

    async def detect(
        self,
        iv_data: dict[str, IVData],
        price_data: dict[str, dict],
        vix_data: dict | None = None,
    ) -> RegimeClassification:
        """Classify market regime from IV rank and price momentum.

        Args:
            iv_data: Mapping of symbol -> IVData from IV engine.
                Symbols with ``iv_rank is None`` are skipped.
            price_data: Mapping of symbol -> dict with at least ``last``
                (current price) and ``prev_close`` (previous close) keys.
                Sourced from Redis ``HGETALL market_data:{symbol}``.
            vix_data: Optional dict with ``last`` key for VIX level.
                Used as supplementary volatility signal if available.

        Returns:
            RegimeClassification with regime, confidence, signals,
            raw indicators, and human-readable reasoning.
        """
        config = self._config

        # --- Compute average IV rank ---
        iv_ranks: list[float] = []
        for symbol, iv in iv_data.items():
            if iv.iv_rank is not None:
                iv_ranks.append(iv.iv_rank)

        total_symbols = len(iv_data)
        iv_rank_avg: float | None = None
        if iv_ranks:
            iv_rank_avg = sum(iv_ranks) / len(iv_ranks)

        # --- Compute average price momentum ---
        momentum_values: list[float] = []
        for symbol, pdata in price_data.items():
            last = _safe_float(pdata.get("last"))
            prev_close = _safe_float(pdata.get("prev_close"))
            if last is not None and prev_close is not None and prev_close > 0:
                pct_change = (last - prev_close) / prev_close
                momentum_values.append(pct_change)

        momentum_avg: float | None = None
        if momentum_values:
            momentum_avg = sum(momentum_values) / len(momentum_values)

        # --- Classify volatility signal ---
        volatility_signal = self._classify_volatility(
            iv_rank_avg, vix_data, config
        )

        # --- Classify trend signal ---
        trend_signal = self._classify_trend(momentum_avg, config)

        # --- Map (trend, volatility) -> raw regime ---
        raw_regime = self._map_regime(trend_signal, volatility_signal)

        # --- Handle insufficient data ---
        if iv_rank_avg is None and momentum_avg is None:
            logger.warning(
                "insufficient_data_for_regime",
                iv_symbols=total_symbols,
                iv_ranks_available=len(iv_ranks),
                price_symbols=len(price_data),
                momentum_available=len(momentum_values),
            )
            classification = RegimeClassification(
                regime=MarketRegime.UNKNOWN,
                confidence=0.0,
                trend_signal="neutral",
                volatility_signal="normal",
                indicators={
                    "iv_rank_avg": None,
                    "momentum_avg": None,
                    "iv_symbols_total": total_symbols,
                    "iv_ranks_available": len(iv_ranks),
                    "price_symbols_total": len(price_data),
                    "momentum_available": len(momentum_values),
                    "vix": _safe_float(vix_data.get("last"))
                    if vix_data
                    else None,
                },
                reasoning=(
                    "Insufficient data for regime classification. "
                    f"IV rank available for {len(iv_ranks)}/{total_symbols} "
                    f"symbols, momentum for {len(momentum_values)}/"
                    f"{len(price_data)} symbols. "
                    "Defaulting to UNKNOWN regime with zero confidence."
                ),
                previous_regime=self._current_regime,
            )
            return classification

        # --- Apply hysteresis ---
        previous_regime = self._current_regime
        self._apply_hysteresis(raw_regime)

        # --- Compute confidence ---
        confidence = self._compute_confidence(
            iv_ranks, total_symbols, momentum_values, price_data
        )

        # --- Build indicators dict ---
        indicators = {
            "iv_rank_avg": round(iv_rank_avg, 2) if iv_rank_avg is not None else None,
            "momentum_avg": (
                round(momentum_avg, 6) if momentum_avg is not None else None
            ),
            "iv_symbols_total": total_symbols,
            "iv_ranks_available": len(iv_ranks),
            "price_symbols_total": len(price_data),
            "momentum_available": len(momentum_values),
            "vix": _safe_float(vix_data.get("last")) if vix_data else None,
            "raw_regime": raw_regime.value,
            "hysteresis_count": self._consecutive_count,
            "hysteresis_threshold": config.hysteresis_count,
        }

        # --- Build reasoning ---
        reasoning = self._build_reasoning(
            iv_rank_avg,
            momentum_avg,
            trend_signal,
            volatility_signal,
            raw_regime,
            self._current_regime,
            vix_data,
        )

        classification = RegimeClassification(
            regime=self._current_regime,
            confidence=confidence,
            trend_signal=trend_signal,
            volatility_signal=volatility_signal,
            indicators=indicators,
            reasoning=reasoning,
            previous_regime=previous_regime,
        )

        logger.info(
            "regime_detected",
            regime=self._current_regime.value,
            confidence=confidence,
            trend=trend_signal,
            volatility=volatility_signal,
            iv_rank_avg=iv_rank_avg,
            momentum_avg=momentum_avg,
        )

        return classification

    def get_strategy_weights(self, regime: MarketRegime) -> dict[str, float]:
        """Return strategy weight distribution for a regime.

        Args:
            regime: The market regime to look up weights for.

        Returns:
            Dict mapping strategy name to weight (0.0-1.0). Falls back
            to UNKNOWN weights if regime is not found in the mapping.
        """
        return REGIME_STRATEGY_WEIGHTS.get(
            regime, REGIME_STRATEGY_WEIGHTS[MarketRegime.UNKNOWN]
        )

    # -------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------

    @staticmethod
    def _classify_volatility(
        iv_rank_avg: float | None,
        vix_data: dict | None,
        config: RegimeConfig,
    ) -> str:
        """Classify volatility signal from IV rank and optional VIX."""
        iv_signal = "normal"
        if iv_rank_avg is not None:
            if iv_rank_avg > config.iv_rank_high_threshold:
                iv_signal = "high"
            elif iv_rank_avg < config.iv_rank_low_threshold:
                iv_signal = "low"

        # VIX as supplementary signal -- use the more extreme reading
        if vix_data is not None:
            vix_level = _safe_float(vix_data.get("last"))
            if vix_level is not None:
                if vix_level > config.vix_high_threshold:
                    # VIX says high vol -- upgrade if IV was normal/low
                    if iv_signal != "high":
                        iv_signal = "high"
                elif vix_level < config.vix_low_threshold:
                    # VIX says low vol -- only downgrade if IV was normal
                    if iv_signal == "normal":
                        iv_signal = "low"

        return iv_signal

    @staticmethod
    def _classify_trend(
        momentum_avg: float | None,
        config: RegimeConfig,
    ) -> str:
        """Classify trend signal from average price momentum."""
        if momentum_avg is None:
            return "neutral"
        if momentum_avg > config.momentum_bull_threshold:
            return "bullish"
        if momentum_avg < config.momentum_bear_threshold:
            return "bearish"
        return "neutral"

    @staticmethod
    def _map_regime(trend: str, volatility: str) -> MarketRegime:
        """Map (trend, volatility) pair to a MarketRegime."""
        if trend == "bullish":
            if volatility == "high":
                return MarketRegime.BULL_VOLATILE
            return MarketRegime.BULL_QUIET
        if trend == "bearish":
            if volatility == "high":
                return MarketRegime.BEAR_VOLATILE
            return MarketRegime.BEAR_QUIET
        # neutral trend
        return MarketRegime.SIDEWAYS

    def _apply_hysteresis(self, raw_regime: MarketRegime) -> None:
        """Apply hysteresis to prevent regime whiplash.

        Only updates ``_current_regime`` when the same raw regime has
        been detected for ``config.hysteresis_count`` consecutive calls.
        """
        if raw_regime == self._current_regime:
            # Regime matches current -- reset pending counter
            self._consecutive_count = 0
            self._pending_regime = None
            return

        if raw_regime == self._pending_regime:
            # Same pending regime seen again -- increment counter
            self._consecutive_count += 1
        else:
            # New pending regime -- reset counter
            self._pending_regime = raw_regime
            self._consecutive_count = 1

        # Switch regime only when threshold reached
        if self._consecutive_count >= self._config.hysteresis_count:
            logger.info(
                "regime_switch",
                from_regime=self._current_regime.value,
                to_regime=raw_regime.value,
                consecutive_count=self._consecutive_count,
            )
            self._current_regime = raw_regime
            self._consecutive_count = 0
            self._pending_regime = None

    def _compute_confidence(
        self,
        iv_ranks: list[float],
        total_symbols: int,
        momentum_values: list[float],
        price_data: dict[str, dict],
    ) -> float:
        """Compute confidence score for the regime classification.

        Confidence is built from:
        - Base: 0.5
        - +0.2 if IV rank data available for >50% of symbols
        - +0.2 if price momentum data available
        - +0.1 if regime is consistent (hysteresis counter is 0,
          meaning current regime matches raw detection)
        """
        confidence = 0.5

        # IV rank data coverage
        if total_symbols > 0 and len(iv_ranks) / total_symbols > 0.5:
            confidence += 0.2

        # Price momentum data available
        if momentum_values:
            confidence += 0.2

        # Regime consistency (hysteresis passed or matches current)
        if self._consecutive_count == 0 and self._pending_regime is None:
            confidence += 0.1

        return min(confidence, 1.0)

    @staticmethod
    def _build_reasoning(
        iv_rank_avg: float | None,
        momentum_avg: float | None,
        trend_signal: str,
        volatility_signal: str,
        raw_regime: MarketRegime,
        confirmed_regime: MarketRegime,
        vix_data: dict | None,
    ) -> str:
        """Build human-readable reasoning string."""
        parts: list[str] = []

        # IV rank assessment
        if iv_rank_avg is not None:
            parts.append(
                f"Average IV rank is {iv_rank_avg:.1f} "
                f"(volatility signal: {volatility_signal})."
            )
        else:
            parts.append("No IV rank data available.")

        # VIX assessment
        if vix_data is not None:
            vix_level = _safe_float(vix_data.get("last"))
            if vix_level is not None:
                parts.append(f"VIX at {vix_level:.1f}.")

        # Momentum assessment
        if momentum_avg is not None:
            pct_str = f"{momentum_avg * 100:.2f}%"
            parts.append(
                f"Average price momentum is {pct_str} "
                f"(trend signal: {trend_signal})."
            )
        else:
            parts.append("No price momentum data available.")

        # Regime mapping
        parts.append(f"Raw regime detection: {raw_regime.value}.")

        # Hysteresis note
        if raw_regime != confirmed_regime:
            parts.append(
                f"Hysteresis active: confirmed regime remains "
                f"{confirmed_regime.value} (pending: {raw_regime.value})."
            )
        else:
            parts.append(f"Confirmed regime: {confirmed_regime.value}.")

        return " ".join(parts)


def _safe_float(value: object) -> float | None:
    """Convert a value to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
