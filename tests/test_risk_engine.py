"""Comprehensive tests for all risk engine components.

Covers:
- Position sizing (RISK-01)
- Greeks exposure (RISK-02)
- Circuit breaker daily/weekly loss limits (RISK-03)
- Strategy restrictions including naked options (RISK-04)
- Fail-safe wrapper (RISK-05)
- Margin check parsing and evaluation (RISK-06)
- Circuit breaker crash recovery / persistence (RISK-07)
- RiskManager orchestrator integration
- Config validation
- Dry-run mode
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest
from pydantic import ValidationError

from trading.risk.circuit_breaker import CircuitBreaker
from trading.risk.config import (
    GreeksLimits,
    LossLimits,
    PositionLimits,
    RiskLimitsConfig,
    RiskLimitsProfile,
    StrategyRestrictions,
)
from trading.risk.evaluators import evaluate_position_size, evaluate_strategy_restrictions
from trading.risk.greeks import PortfolioGreeks, evaluate_greeks_exposure
from trading.risk.manager import RiskManager, evaluate_with_failsafe
from trading.risk.margin_check import _parse_margin_str, evaluate_margin
from trading.risk.models import (
    GreeksImpact,
    MarginResult,
    RiskDecision,
    TradeLeg,
    TradeProposal,
    ViolatedRule,
)
from trading.risk.repository import RiskRepository


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def make_proposal(**kwargs) -> TradeProposal:
    """Create a test TradeProposal with sensible defaults."""
    defaults = {
        "legs": [TradeLeg(symbol="SPY", sec_type="OPT", action="BUY", quantity=2)],
        "estimated_greeks": GreeksImpact(delta=50, gamma=5, theta=-10, vega=20),
        "max_loss": 1000.0,
        "strategy_type": "vertical_spread",
        "account_value": 100_000.0,
    }
    defaults.update(kwargs)
    return TradeProposal(**defaults)


def make_limits(**kwargs) -> PositionLimits:
    """Create PositionLimits with overridable defaults."""
    defaults = {
        "max_dollars": 5000.0,
        "max_contracts": 10,
        "max_position_pct": 0.05,
    }
    defaults.update(kwargs)
    return PositionLimits(**defaults)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_redis():
    """Create a fakeredis instance for testing."""
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def mock_repository():
    """Create a mock RiskRepository."""
    repo = AsyncMock(spec=RiskRepository)
    repo.save_decision = AsyncMock()
    repo.save_circuit_breaker_state = AsyncMock()
    repo.load_circuit_breaker_state = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_circuit_breaker():
    """Create a mock CircuitBreaker that always passes."""
    cb = AsyncMock(spec=CircuitBreaker)
    cb.check = AsyncMock(return_value=None)
    cb.check_and_reset = AsyncMock()
    return cb


@pytest.fixture
def default_limits() -> RiskLimitsProfile:
    """Create a RiskLimitsProfile with default values."""
    return RiskLimitsProfile()


# ============================================================================
# Position Sizing Tests (RISK-01)
# ============================================================================


class TestPositionSizing:
    """Tests for evaluate_position_size evaluator."""

    def test_position_size_passes_within_limits(self):
        """All limits satisfied returns None (pass)."""
        proposal = make_proposal(max_loss=1000.0)
        limits = make_limits(max_dollars=5000.0, max_contracts=10, max_position_pct=0.05)
        result = evaluate_position_size(proposal, limits)
        assert result is None

    def test_position_size_rejects_dollar_limit(self):
        """max_loss exceeding max_dollars returns rejection."""
        proposal = make_proposal(max_loss=6000.0)
        limits = make_limits(max_dollars=5000.0)
        result = evaluate_position_size(proposal, limits)
        assert result is not None
        assert result.approved is False
        assert result.violated_rule == ViolatedRule.POSITION_SIZE_DOLLARS

    def test_position_size_rejects_contract_limit(self):
        """Total OPT contracts exceeding max_contracts returns rejection."""
        legs = [
            TradeLeg(symbol="SPY", sec_type="OPT", action="BUY", quantity=6),
            TradeLeg(symbol="SPY", sec_type="OPT", action="SELL", quantity=6),
        ]
        proposal = make_proposal(legs=legs, max_loss=1000.0)
        limits = make_limits(max_contracts=10)
        result = evaluate_position_size(proposal, limits)
        assert result is not None
        assert result.approved is False
        assert result.violated_rule == ViolatedRule.POSITION_SIZE_CONTRACTS

    def test_position_size_rejects_portfolio_pct(self):
        """max_loss/account_value exceeding max_position_pct returns rejection."""
        proposal = make_proposal(max_loss=4000.0, account_value=50_000.0)
        limits = make_limits(max_position_pct=0.05)
        # 4000/50000 = 8% > 5%
        result = evaluate_position_size(proposal, limits)
        assert result is not None
        assert result.approved is False
        assert result.violated_rule == ViolatedRule.POSITION_SIZE_PERCENT

    def test_position_size_zero_account_value_skips_pct(self):
        """account_value=0 skips percentage check (no division by zero)."""
        proposal = make_proposal(max_loss=1000.0, account_value=0.0)
        limits = make_limits(max_dollars=5000.0, max_contracts=10, max_position_pct=0.05)
        result = evaluate_position_size(proposal, limits)
        assert result is None

    def test_position_size_stock_legs_not_counted(self):
        """STK legs are not counted toward contract limit."""
        legs = [
            TradeLeg(symbol="SPY", sec_type="STK", action="BUY", quantity=100),
            TradeLeg(symbol="SPY", sec_type="OPT", action="BUY", quantity=2),
        ]
        proposal = make_proposal(legs=legs, max_loss=1000.0)
        limits = make_limits(max_contracts=5)
        result = evaluate_position_size(proposal, limits)
        assert result is None


# ============================================================================
# Greeks Exposure Tests (RISK-02)
# ============================================================================


class TestGreeksExposure:
    """Tests for evaluate_greeks_exposure evaluator."""

    def test_greeks_passes_within_limits(self):
        """Projected Greeks within all caps returns None (pass)."""
        proposal = make_proposal(
            estimated_greeks=GreeksImpact(delta=50, gamma=5, theta=-10, vega=20)
        )
        limits = GreeksLimits(max_delta=500, max_gamma=100, max_theta=-500, max_vega=1000)
        result = evaluate_greeks_exposure(proposal, limits)
        assert result is None

    def test_greeks_rejects_delta_exposure(self):
        """Projected delta exceeding max_delta returns rejection."""
        proposal = make_proposal(
            estimated_greeks=GreeksImpact(delta=600, gamma=5, theta=-10, vega=20)
        )
        limits = GreeksLimits(max_delta=500)
        result = evaluate_greeks_exposure(proposal, limits)
        assert result is not None
        assert result.violated_rule == ViolatedRule.DELTA_EXPOSURE

    def test_greeks_rejects_theta_exposure(self):
        """Projected theta more negative than max_theta returns rejection."""
        proposal = make_proposal(
            estimated_greeks=GreeksImpact(delta=50, gamma=5, theta=-600, vega=20)
        )
        limits = GreeksLimits(max_theta=-500)
        result = evaluate_greeks_exposure(proposal, limits)
        assert result is not None
        assert result.violated_rule == ViolatedRule.THETA_EXPOSURE

    def test_greeks_none_portfolio_uses_zero(self):
        """current_portfolio_greeks=None treated as zero baseline."""
        proposal = make_proposal(
            estimated_greeks=GreeksImpact(delta=50, gamma=5, theta=-10, vega=20)
        )
        limits = GreeksLimits(max_delta=500, max_gamma=100, max_theta=-500, max_vega=1000)
        result = evaluate_greeks_exposure(proposal, limits, current_portfolio_greeks=None)
        assert result is None

    def test_greeks_aggregation_with_short_positions(self):
        """Short positions with correct sign aggregate properly."""
        # Current portfolio: delta=400 (long-biased)
        # Trade adds delta=-50 (short delta) => projected 350 (within 500 limit)
        current = PortfolioGreeks(delta=400, gamma=0, theta=0, vega=0)
        proposal = make_proposal(
            estimated_greeks=GreeksImpact(delta=-50, gamma=0, theta=0, vega=0)
        )
        limits = GreeksLimits(max_delta=500, max_gamma=100, max_theta=-500, max_vega=1000)
        result = evaluate_greeks_exposure(proposal, limits, current_portfolio_greeks=current)
        assert result is None

    def test_greeks_rejects_gamma_exposure(self):
        """Projected gamma exceeding max_gamma returns rejection."""
        proposal = make_proposal(
            estimated_greeks=GreeksImpact(delta=0, gamma=150, theta=0, vega=0)
        )
        limits = GreeksLimits(max_gamma=100)
        result = evaluate_greeks_exposure(proposal, limits)
        assert result is not None
        assert result.violated_rule == ViolatedRule.GAMMA_EXPOSURE

    def test_greeks_rejects_vega_exposure(self):
        """Projected vega exceeding max_vega returns rejection."""
        proposal = make_proposal(
            estimated_greeks=GreeksImpact(delta=0, gamma=0, theta=0, vega=1500)
        )
        limits = GreeksLimits(max_vega=1000)
        result = evaluate_greeks_exposure(proposal, limits)
        assert result is not None
        assert result.violated_rule == ViolatedRule.VEGA_EXPOSURE


# ============================================================================
# Strategy Restriction Tests (RISK-04)
# ============================================================================


class TestStrategyRestrictions:
    """Tests for evaluate_strategy_restrictions evaluator."""

    def test_strategy_allowed_passes(self):
        """Strategy in allowlist with no naked options returns None."""
        proposal = make_proposal(strategy_type="vertical_spread")
        restrictions = StrategyRestrictions()
        result = evaluate_strategy_restrictions(proposal, restrictions)
        assert result is None

    def test_strategy_disallowed_rejects(self):
        """Strategy not in allowlist returns rejection."""
        proposal = make_proposal(strategy_type="straddle")
        restrictions = StrategyRestrictions()
        result = evaluate_strategy_restrictions(proposal, restrictions)
        assert result is not None
        assert result.violated_rule == ViolatedRule.STRATEGY_RESTRICTED

    def test_naked_option_detected_rejects(self):
        """Short option without covering long is rejected."""
        legs = [
            TradeLeg(symbol="SPY", sec_type="OPT", action="SELL", quantity=1, right="C"),
        ]
        proposal = make_proposal(legs=legs, strategy_type="covered_call")
        restrictions = StrategyRestrictions(allow_naked_options=False)
        result = evaluate_strategy_restrictions(proposal, restrictions)
        assert result is not None
        assert result.violated_rule == ViolatedRule.NAKED_OPTION

    def test_spread_not_naked(self):
        """Short option with covering long in same proposal passes naked check."""
        legs = [
            TradeLeg(symbol="SPY", sec_type="OPT", action="SELL", quantity=1, right="C"),
            TradeLeg(symbol="SPY", sec_type="OPT", action="BUY", quantity=1, right="C"),
        ]
        proposal = make_proposal(legs=legs, strategy_type="vertical_spread")
        restrictions = StrategyRestrictions(allow_naked_options=False)
        result = evaluate_strategy_restrictions(proposal, restrictions)
        assert result is None

    def test_naked_allowed_when_configured(self):
        """allow_naked_options=True permits naked shorts."""
        legs = [
            TradeLeg(symbol="SPY", sec_type="OPT", action="SELL", quantity=1, right="P"),
        ]
        proposal = make_proposal(legs=legs, strategy_type="cash_secured_put")
        restrictions = StrategyRestrictions(allow_naked_options=True)
        result = evaluate_strategy_restrictions(proposal, restrictions)
        assert result is None


# ============================================================================
# Circuit Breaker Tests (RISK-03, RISK-07)
# ============================================================================


class TestCircuitBreaker:
    """Tests for CircuitBreaker using fakeredis."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_not_halted_passes(self, fake_redis, mock_repository):
        """No halt active returns None (pass)."""
        limits = LossLimits(daily_max_loss=1000, weekly_max_loss=3000)
        cb = CircuitBreaker(
            redis=fake_redis,
            repository=mock_repository,
            mode="paper",
            limits=limits,
        )
        result = await cb.check()
        assert result is None

    @pytest.mark.asyncio
    async def test_circuit_breaker_daily_halt_rejects(self, fake_redis, mock_repository):
        """Daily halt active returns rejection with DAILY_LOSS_LIMIT."""
        limits = LossLimits(daily_max_loss=1000, weekly_max_loss=3000)
        cb = CircuitBreaker(
            redis=fake_redis,
            repository=mock_repository,
            mode="paper",
            limits=limits,
        )
        # Manually set halt state in Redis
        await fake_redis.hset(
            "risk:circuit_breaker:paper",
            mapping={"daily_halted": "true", "halted_at": "2026-01-01T10:00:00", "daily_realized_loss": "1500"},
        )
        result = await cb.check()
        assert result is not None
        assert result.approved is False
        assert result.violated_rule == ViolatedRule.DAILY_LOSS_LIMIT

    @pytest.mark.asyncio
    async def test_circuit_breaker_weekly_halt_rejects(self, fake_redis, mock_repository):
        """Weekly halt active returns rejection with WEEKLY_LOSS_LIMIT."""
        limits = LossLimits(daily_max_loss=1000, weekly_max_loss=3000)
        cb = CircuitBreaker(
            redis=fake_redis,
            repository=mock_repository,
            mode="paper",
            limits=limits,
        )
        await fake_redis.hset(
            "risk:circuit_breaker:paper",
            mapping={"weekly_halted": "true", "halted_at": "2026-01-01T10:00:00", "weekly_realized_loss": "4000"},
        )
        result = await cb.check()
        assert result is not None
        assert result.approved is False
        assert result.violated_rule == ViolatedRule.WEEKLY_LOSS_LIMIT

    @pytest.mark.asyncio
    async def test_record_loss_triggers_daily_halt(self, fake_redis, mock_repository):
        """Loss exceeding daily limit activates daily halt."""
        limits = LossLimits(daily_max_loss=1000, weekly_max_loss=5000)
        cb = CircuitBreaker(
            redis=fake_redis,
            repository=mock_repository,
            mode="paper",
            limits=limits,
        )
        # Record loss that exceeds daily limit
        await cb.record_realized_loss(1100.0)

        # Verify halt was set in Redis
        state = await fake_redis.hgetall("risk:circuit_breaker:paper")
        assert state.get("daily_halted") == "true"
        # Weekly should NOT be halted (1100 < 5000)
        assert state.get("weekly_halted", "false") != "true"
        # Verify persisted to Postgres
        mock_repository.save_circuit_breaker_state.assert_called()

    @pytest.mark.asyncio
    async def test_record_loss_triggers_weekly_halt(self, fake_redis, mock_repository):
        """Loss exceeding weekly limit activates weekly halt."""
        limits = LossLimits(daily_max_loss=10_000, weekly_max_loss=3000)
        cb = CircuitBreaker(
            redis=fake_redis,
            repository=mock_repository,
            mode="paper",
            limits=limits,
        )
        await cb.record_realized_loss(3500.0)

        state = await fake_redis.hgetall("risk:circuit_breaker:paper")
        assert state.get("weekly_halted") == "true"

    @pytest.mark.asyncio
    async def test_daily_reset_clears_daily_not_weekly(self, fake_redis, mock_repository):
        """Daily reset clears daily loss/halt but does not touch weekly state."""
        limits = LossLimits(daily_max_loss=1000, weekly_max_loss=5000)
        cb = CircuitBreaker(
            redis=fake_redis,
            repository=mock_repository,
            mode="paper",
            limits=limits,
        )
        # Set up both daily and weekly halt state
        await fake_redis.hset(
            "risk:circuit_breaker:paper",
            mapping={
                "daily_halted": "true",
                "weekly_halted": "true",
                "daily_realized_loss": "1500",
                "weekly_realized_loss": "6000",
                "halted_at": "2026-01-01T10:00:00",
            },
        )

        # Simulate daily reset by calling check_and_reset with time after market open
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        from unittest.mock import patch as mock_patch

        ET = ZoneInfo("America/New_York")
        # Use a Tuesday at 10:00 AM ET (after market open, not Monday)
        fake_now = datetime(2026, 4, 7, 14, 0, 0, tzinfo=timezone.utc)  # Tue 10am ET
        with mock_patch("trading.risk.circuit_breaker.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await cb.check_and_reset()

        state = await fake_redis.hgetall("risk:circuit_breaker:paper")
        # Daily should be reset
        assert state.get("daily_halted") == "false"
        assert state.get("daily_realized_loss") == "0"
        # Weekly should remain halted (not a Monday)
        assert state.get("weekly_halted") == "true"
        assert state.get("weekly_realized_loss") == "6000"

    @pytest.mark.asyncio
    async def test_record_zero_loss_ignored(self, fake_redis, mock_repository):
        """Recording zero or negative loss is a no-op."""
        limits = LossLimits(daily_max_loss=1000, weekly_max_loss=3000)
        cb = CircuitBreaker(
            redis=fake_redis,
            repository=mock_repository,
            mode="paper",
            limits=limits,
        )
        await cb.record_realized_loss(0.0)
        await cb.record_realized_loss(-100.0)

        state = await fake_redis.hgetall("risk:circuit_breaker:paper")
        # Nothing should have been written
        assert state == {} or state.get("daily_realized_loss", "0") == "0"

    @pytest.mark.asyncio
    async def test_load_from_db_restores_state(self, fake_redis, mock_repository):
        """load_from_db copies Postgres state into Redis for crash recovery."""
        limits = LossLimits(daily_max_loss=1000, weekly_max_loss=3000)
        cb = CircuitBreaker(
            redis=fake_redis,
            repository=mock_repository,
            mode="paper",
            limits=limits,
        )

        # Simulate DB record
        from datetime import datetime, timezone

        mock_record = MagicMock()
        mock_record.halt_type = "daily"
        mock_record.halted = True
        mock_record.halted_at = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        mock_record.daily_realized_loss = 1500.0
        mock_record.weekly_realized_loss = 2000.0

        mock_repository.load_circuit_breaker_state.return_value = [mock_record]

        await cb.load_from_db()

        state = await fake_redis.hgetall("risk:circuit_breaker:paper")
        assert state.get("daily_halted") == "true"
        assert state.get("daily_realized_loss") == "1500.0"
        assert state.get("weekly_realized_loss") == "2000.0"


# ============================================================================
# Margin Check Tests (RISK-06)
# ============================================================================


class TestMarginCheck:
    """Tests for margin string parsing and margin evaluation."""

    def test_parse_margin_str_valid(self):
        """Normal float string parses correctly."""
        result = _parse_margin_str("12345.67")
        assert result == 12345.67

    def test_parse_margin_str_unset_double(self):
        """UNSET_DOUBLE sentinel returns None."""
        result = _parse_margin_str("1.7976931348623157e+308")
        assert result is None

    def test_parse_margin_str_empty(self):
        """Empty string returns None."""
        result = _parse_margin_str("")
        assert result is None

    def test_parse_margin_str_none(self):
        """None input returns None."""
        result = _parse_margin_str(None)
        assert result is None

    def test_parse_margin_str_invalid(self):
        """Non-numeric string returns None."""
        result = _parse_margin_str("not_a_number")
        assert result is None

    def test_evaluate_margin_timeout_passes(self):
        """timed_out=True returns None (pass-through)."""
        margin = MarginResult(timed_out=True)
        result = evaluate_margin(margin, account_value=100_000)
        assert result is None

    def test_evaluate_margin_negative_equity_rejects(self):
        """equity_with_loan_after <= 0 returns rejection."""
        margin = MarginResult(
            equity_with_loan_after=-5000.0,
            init_margin_after=50000.0,
            timed_out=False,
        )
        result = evaluate_margin(margin, account_value=100_000)
        assert result is not None
        assert result.approved is False
        assert result.violated_rule == ViolatedRule.MARGIN_INSUFFICIENT

    def test_evaluate_margin_init_exceeds_account_rejects(self):
        """init_margin_after > account_value returns rejection."""
        margin = MarginResult(
            equity_with_loan_after=50000.0,
            init_margin_after=150_000.0,
            timed_out=False,
        )
        result = evaluate_margin(margin, account_value=100_000)
        assert result is not None
        assert result.approved is False
        assert result.violated_rule == ViolatedRule.MARGIN_CHECK_REJECTED

    def test_evaluate_margin_all_pass(self):
        """Good margin values return None (pass)."""
        margin = MarginResult(
            equity_with_loan_after=80000.0,
            init_margin_after=50000.0,
            maint_margin_after=40000.0,
            timed_out=False,
        )
        result = evaluate_margin(margin, account_value=100_000)
        assert result is None


# ============================================================================
# RiskManager Integration Tests
# ============================================================================


class TestRiskManagerIntegration:
    """Tests for RiskManager orchestrator with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_check_trade_approved_all_pass(
        self, mock_circuit_breaker, mock_repository
    ):
        """All checks pass returns approved=True."""
        limits = RiskLimitsProfile()
        rm = RiskManager(
            limits=limits,
            circuit_breaker=mock_circuit_breaker,
            repository=mock_repository,
            ib=None,
            mode="paper",
        )
        proposal = make_proposal(max_loss=1000.0)
        decision = await rm.check_trade(proposal)
        assert decision.approved is True
        assert decision.violated_rule is None
        # Verify persisted
        mock_repository.save_decision.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_trade_short_circuits_on_first_violation(
        self, mock_circuit_breaker, mock_repository
    ):
        """Exceeding dollar limit stops before Greeks check runs."""
        limits = RiskLimitsProfile(
            position=PositionLimits(max_dollars=500.0),
        )
        rm = RiskManager(
            limits=limits,
            circuit_breaker=mock_circuit_breaker,
            repository=mock_repository,
            ib=None,
            mode="paper",
        )
        # max_loss=1000 > max_dollars=500 -> rejected at position sizing
        proposal = make_proposal(max_loss=1000.0)
        decision = await rm.check_trade(proposal)
        assert decision.approved is False
        assert decision.violated_rule == ViolatedRule.POSITION_SIZE_DOLLARS

    @pytest.mark.asyncio
    async def test_dry_run_sets_flag(self, mock_circuit_breaker, mock_repository):
        """dry_run flag is propagated on returned decision."""
        limits = RiskLimitsProfile()
        rm = RiskManager(
            limits=limits,
            circuit_breaker=mock_circuit_breaker,
            repository=mock_repository,
            ib=None,
            mode="paper",
        )
        proposal = make_proposal(max_loss=1000.0)
        decision = await rm.check_trade(proposal, dry_run=True)
        assert decision.dry_run is True

    @pytest.mark.asyncio
    async def test_emergency_halt_blocks_all(self, mock_circuit_breaker, mock_repository):
        """emergency_halt=True rejects before any other check."""
        limits = RiskLimitsProfile(emergency_halt=True)
        rm = RiskManager(
            limits=limits,
            circuit_breaker=mock_circuit_breaker,
            repository=mock_repository,
            ib=None,
            mode="paper",
        )
        proposal = make_proposal()
        decision = await rm.check_trade(proposal)
        assert decision.approved is False
        assert decision.violated_rule == ViolatedRule.EMERGENCY_HALT
        # Circuit breaker should NOT have been called (short-circuit)
        mock_circuit_breaker.check.assert_not_called()

    @pytest.mark.asyncio
    async def test_circuit_breaker_rejection_propagated(
        self, mock_repository
    ):
        """Circuit breaker halt rejection propagates through RiskManager."""
        cb = AsyncMock(spec=CircuitBreaker)
        cb.check_and_reset = AsyncMock()
        cb.check = AsyncMock(return_value=RiskDecision(
            approved=False,
            violated_rule=ViolatedRule.DAILY_LOSS_LIMIT,
            details="Daily loss limit breached",
        ))

        limits = RiskLimitsProfile()
        rm = RiskManager(
            limits=limits,
            circuit_breaker=cb,
            repository=mock_repository,
            ib=None,
            mode="paper",
        )
        proposal = make_proposal()
        decision = await rm.check_trade(proposal)
        assert decision.approved is False
        assert decision.violated_rule == ViolatedRule.DAILY_LOSS_LIMIT

    @pytest.mark.asyncio
    async def test_persist_error_does_not_block(
        self, mock_circuit_breaker
    ):
        """Persistence failure logs warning but does not prevent evaluation."""
        bad_repo = AsyncMock(spec=RiskRepository)
        bad_repo.save_decision = AsyncMock(side_effect=Exception("DB down"))

        limits = RiskLimitsProfile()
        rm = RiskManager(
            limits=limits,
            circuit_breaker=mock_circuit_breaker,
            repository=bad_repo,
            ib=None,
            mode="paper",
        )
        proposal = make_proposal(max_loss=1000.0)
        # Should NOT raise even though persistence fails
        decision = await rm.check_trade(proposal)
        assert decision.approved is True


# ============================================================================
# Fail-Safe Tests (RISK-05)
# ============================================================================


class TestFailSafe:
    """Tests for evaluate_with_failsafe wrapper."""

    @pytest.mark.asyncio
    async def test_failsafe_timeout_rejects(self, mock_circuit_breaker, mock_repository):
        """Timeout returns RISK_MANAGER_UNAVAILABLE rejection."""
        limits = RiskLimitsProfile()
        rm = RiskManager(
            limits=limits,
            circuit_breaker=mock_circuit_breaker,
            repository=mock_repository,
            ib=None,
            mode="paper",
        )

        # Make check_trade hang forever
        async def slow_check(*args, **kwargs):
            await asyncio.sleep(100)
            return RiskDecision(approved=True)

        rm.check_trade = slow_check

        proposal = make_proposal()
        decision = await evaluate_with_failsafe(rm, proposal, timeout=0.1)
        assert decision.approved is False
        assert decision.violated_rule == ViolatedRule.RISK_MANAGER_UNAVAILABLE

    @pytest.mark.asyncio
    async def test_failsafe_exception_rejects(self, mock_circuit_breaker, mock_repository):
        """Any exception returns RISK_MANAGER_UNAVAILABLE rejection."""
        limits = RiskLimitsProfile()
        rm = RiskManager(
            limits=limits,
            circuit_breaker=mock_circuit_breaker,
            repository=mock_repository,
            ib=None,
            mode="paper",
        )

        async def broken_check(*args, **kwargs):
            raise RuntimeError("Something exploded")

        rm.check_trade = broken_check

        proposal = make_proposal()
        decision = await evaluate_with_failsafe(rm, proposal, timeout=5.0)
        assert decision.approved is False
        assert decision.violated_rule == ViolatedRule.RISK_MANAGER_UNAVAILABLE

    @pytest.mark.asyncio
    async def test_failsafe_normal_passthrough(
        self, mock_circuit_breaker, mock_repository
    ):
        """Normal evaluation result passed through unchanged."""
        limits = RiskLimitsProfile()
        rm = RiskManager(
            limits=limits,
            circuit_breaker=mock_circuit_breaker,
            repository=mock_repository,
            ib=None,
            mode="paper",
        )
        proposal = make_proposal(max_loss=1000.0)
        decision = await evaluate_with_failsafe(rm, proposal, timeout=5.0)
        assert decision.approved is True


# ============================================================================
# Config Validation Tests
# ============================================================================


class TestConfigValidation:
    """Tests for risk limits configuration validation."""

    def test_risk_limits_rejects_negative_dollars(self):
        """PositionLimits(max_dollars=-100) raises ValidationError."""
        with pytest.raises(ValidationError):
            PositionLimits(max_dollars=-100)

    def test_risk_limits_rejects_zero_contracts(self):
        """PositionLimits(max_contracts=0) raises ValidationError."""
        with pytest.raises(ValidationError):
            PositionLimits(max_contracts=0)

    def test_risk_limits_rejects_negative_contracts(self):
        """PositionLimits(max_contracts=-1) raises ValidationError."""
        with pytest.raises(ValidationError):
            PositionLimits(max_contracts=-1)

    def test_risk_limits_rejects_pct_over_one(self):
        """PositionLimits(max_position_pct=1.5) raises ValidationError."""
        with pytest.raises(ValidationError):
            PositionLimits(max_position_pct=1.5)

    def test_risk_limits_rejects_zero_dollars(self):
        """PositionLimits(max_dollars=0) raises ValidationError."""
        with pytest.raises(ValidationError):
            PositionLimits(max_dollars=0)

    def test_risk_limits_paper_live_separation(self):
        """RiskLimitsConfig loads different defaults for paper vs live."""
        config = RiskLimitsConfig()
        # Both profiles exist and are independent
        assert config.paper is not None
        assert config.live is not None
        # Changing one does not affect the other
        config.paper.position.max_dollars = 9999.0
        assert config.live.position.max_dollars != 9999.0

    def test_risk_profile_rejects_none_subsection(self):
        """RiskLimitsProfile rejects None for limit subsections."""
        with pytest.raises(ValidationError):
            RiskLimitsProfile(position=None)

    def test_loss_limits_rejects_zero_daily(self):
        """LossLimits rejects daily_max_loss <= 0."""
        with pytest.raises(ValidationError):
            LossLimits(daily_max_loss=0)

    def test_greeks_limits_rejects_negative_delta(self):
        """GreeksLimits rejects max_delta <= 0."""
        with pytest.raises(ValidationError):
            GreeksLimits(max_delta=-100)
