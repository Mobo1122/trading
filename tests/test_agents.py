"""Comprehensive tests for Phase 5 agent pipeline components.

Covers:
- Output contract serialization (Opportunity, ScannerOutput, StrategyProposal, etc.)
- AgentConfig defaults and get_model with/without overrides
- PipelineState initial values and JSON serialization
- Conditional routing (route_after_scan, route_after_risk)
- Agent definitions (tool counts, output types)
- Decision logging (mock session_factory)
- Checkpoint factory validation (rejects asyncpg)
- Pipeline deps and create_pipeline factory
- App wiring (startup creates pipeline_deps)

All tests work WITHOUT an LLM API key.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.graph import END

from trading.agents.config import AgentConfig
from trading.agents.logging import STAGE_ORDER, _get_output_summary, log_agent_decision
from trading.agents.models import (
    ExecutionResult,
    ExecutorOutput,
    Opportunity,
    PipelineResult,
    ProposedLeg,
    RiskAssessment,
    RiskManagerOutput,
    ScannerOutput,
    StrategyProposal,
    StrategistOutput,
)
from trading.agents.pipeline import (
    PipelineDeps,
    create_pipeline,
    route_after_risk,
    route_after_scan,
    run_pipeline,
)
from trading.agents.state import PipelineState


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def make_opportunity(**kwargs) -> Opportunity:
    """Create a test Opportunity with sensible defaults."""
    defaults = {
        "symbol": "SPY",
        "signal_type": "iv_rank_high",
        "confidence": 0.85,
        "iv_rank": 75.0,
        "iv_percentile": 80.0,
        "current_price": 450.0,
        "days_to_earnings": None,
        "reasoning": "High IV rank suggests premium selling opportunity",
    }
    defaults.update(kwargs)
    return Opportunity(**defaults)


def make_proposed_leg(**kwargs) -> ProposedLeg:
    """Create a test ProposedLeg with sensible defaults."""
    defaults = {
        "symbol": "SPY",
        "right": "P",
        "strike": 440.0,
        "expiry": "20260501",
        "action": "SELL",
        "quantity": 1,
        "estimated_price": 2.50,
    }
    defaults.update(kwargs)
    return ProposedLeg(**defaults)


def make_strategy_proposal(**kwargs) -> StrategyProposal:
    """Create a test StrategyProposal with sensible defaults."""
    defaults = {
        "symbol": "SPY",
        "strategy_type": "vertical_spread",
        "legs": [make_proposed_leg()],
        "max_loss": 500.0,
        "max_profit": 250.0,
        "probability_of_profit": 0.65,
        "reasoning": "Bearish vertical spread on high IV",
    }
    defaults.update(kwargs)
    return StrategyProposal(**defaults)


def make_risk_assessment(**kwargs) -> RiskAssessment:
    """Create a test RiskAssessment with sensible defaults."""
    defaults = {
        "proposal_id": "test-proposal-1",
        "deterministic_approved": True,
        "deterministic_details": "All checks passed",
        "llm_risk_score": 3.0,
        "llm_risk_reasoning": "Low risk spread with defined max loss",
        "approved": True,
        "reasoning": "Approved: deterministic passed, risk score 3/10",
    }
    defaults.update(kwargs)
    return RiskAssessment(**defaults)


def make_execution_result(**kwargs) -> ExecutionResult:
    """Create a test ExecutionResult with sensible defaults."""
    defaults = {
        "proposal_id": "test-proposal-1",
        "order_id": "12345",
        "status": "submitted",
        "details": "Order placed for SPY vertical spread",
    }
    defaults.update(kwargs)
    return ExecutionResult(**defaults)


def make_pipeline_state(**kwargs) -> PipelineState:
    """Create a test PipelineState with default empty values."""
    defaults: PipelineState = {
        "watchlist": ["SPY", "QQQ"],
        "opportunities": [],
        "trade_proposals": [],
        "risk_assessments": [],
        "execution_results": [],
        "scanner_reasoning": "",
        "strategist_reasoning": "",
        "risk_reasoning": "",
        "executor_reasoning": "",
        "run_id": "test-run-123",
        "aborted_at": "",
    }
    defaults.update(kwargs)
    return defaults


# ============================================================================
# Output Contract Serialization Tests
# ============================================================================


class TestOutputContracts:
    """Tests that all agent output models serialize/deserialize correctly."""

    def test_opportunity_roundtrip(self):
        """Opportunity model serializes to JSON and back."""
        opp = make_opportunity()
        json_str = opp.model_dump_json()
        restored = Opportunity.model_validate_json(json_str)
        assert restored.symbol == "SPY"
        assert restored.confidence == 0.85
        assert restored.iv_rank == 75.0

    def test_opportunity_validation_bounds(self):
        """Opportunity rejects confidence outside [0, 1]."""
        with pytest.raises(Exception):
            Opportunity(
                symbol="SPY",
                signal_type="test",
                confidence=1.5,
                reasoning="test",
            )

    def test_scanner_output_roundtrip(self):
        """ScannerOutput with nested opportunities serializes correctly."""
        output = ScannerOutput(
            opportunities=[make_opportunity(), make_opportunity(symbol="QQQ")],
            symbols_scanned=5,
            reasoning="Scanned 5 symbols, found 2 opportunities",
        )
        json_str = output.model_dump_json()
        restored = ScannerOutput.model_validate_json(json_str)
        assert len(restored.opportunities) == 2
        assert restored.symbols_scanned == 5
        assert restored.opportunities[1].symbol == "QQQ"

    def test_proposed_leg_roundtrip(self):
        """ProposedLeg serializes with all option fields."""
        leg = make_proposed_leg()
        json_str = leg.model_dump_json()
        restored = ProposedLeg.model_validate_json(json_str)
        assert restored.strike == 440.0
        assert restored.right == "P"
        assert restored.expiry == "20260501"
        assert restored.action == "SELL"

    def test_strategy_proposal_roundtrip(self):
        """StrategyProposal with nested legs serializes correctly."""
        proposal = make_strategy_proposal(
            legs=[
                make_proposed_leg(action="SELL", strike=440.0),
                make_proposed_leg(action="BUY", strike=435.0),
            ]
        )
        json_str = proposal.model_dump_json()
        restored = StrategyProposal.model_validate_json(json_str)
        assert len(restored.legs) == 2
        assert restored.max_loss == 500.0
        assert restored.probability_of_profit == 0.65

    def test_strategy_proposal_probability_bounds(self):
        """StrategyProposal rejects probability_of_profit outside [0, 1]."""
        with pytest.raises(Exception):
            make_strategy_proposal(probability_of_profit=1.5)

    def test_strategist_output_roundtrip(self):
        """StrategistOutput with nested proposals serializes correctly."""
        output = StrategistOutput(
            proposals=[make_strategy_proposal()],
            reasoning="Constructed 1 vertical spread",
        )
        json_str = output.model_dump_json()
        restored = StrategistOutput.model_validate_json(json_str)
        assert len(restored.proposals) == 1
        assert restored.reasoning == "Constructed 1 vertical spread"

    def test_risk_assessment_roundtrip(self):
        """RiskAssessment serializes with deterministic + LLM fields."""
        assessment = make_risk_assessment()
        json_str = assessment.model_dump_json()
        restored = RiskAssessment.model_validate_json(json_str)
        assert restored.deterministic_approved is True
        assert restored.llm_risk_score == 3.0
        assert restored.approved is True

    def test_risk_assessment_score_bounds(self):
        """RiskAssessment rejects llm_risk_score outside [1, 10]."""
        with pytest.raises(Exception):
            make_risk_assessment(llm_risk_score=11.0)
        with pytest.raises(Exception):
            make_risk_assessment(llm_risk_score=0.0)

    def test_risk_manager_output_roundtrip(self):
        """RiskManagerOutput with nested assessments serializes correctly."""
        output = RiskManagerOutput(
            assessments=[
                make_risk_assessment(approved=True),
                make_risk_assessment(proposal_id="test-2", approved=False),
            ],
            reasoning="1 approved, 1 rejected",
        )
        json_str = output.model_dump_json()
        restored = RiskManagerOutput.model_validate_json(json_str)
        assert len(restored.assessments) == 2
        approved = [a for a in restored.assessments if a.approved]
        assert len(approved) == 1

    def test_execution_result_roundtrip(self):
        """ExecutionResult serializes with optional order_id."""
        result = make_execution_result()
        json_str = result.model_dump_json()
        restored = ExecutionResult.model_validate_json(json_str)
        assert restored.order_id == "12345"
        assert restored.status == "submitted"

    def test_execution_result_no_order_id(self):
        """ExecutionResult serializes with None order_id for failed trades."""
        result = make_execution_result(order_id=None, status="failed")
        json_str = result.model_dump_json()
        restored = ExecutionResult.model_validate_json(json_str)
        assert restored.order_id is None
        assert restored.status == "failed"

    def test_executor_output_roundtrip(self):
        """ExecutorOutput with nested results serializes correctly."""
        output = ExecutorOutput(
            results=[make_execution_result()],
            reasoning="Submitted 1 order",
        )
        json_str = output.model_dump_json()
        restored = ExecutorOutput.model_validate_json(json_str)
        assert len(restored.results) == 1

    def test_pipeline_result_full(self):
        """PipelineResult aggregates all stage outputs."""
        result = PipelineResult(
            run_id="test-run-1",
            scanner_output=ScannerOutput(
                opportunities=[make_opportunity()],
                symbols_scanned=5,
                reasoning="test",
            ),
            strategist_output=StrategistOutput(
                proposals=[make_strategy_proposal()],
                reasoning="test",
            ),
            risk_output=RiskManagerOutput(
                assessments=[make_risk_assessment()],
                reasoning="test",
            ),
            executor_output=ExecutorOutput(
                results=[make_execution_result()],
                reasoning="test",
            ),
            completed_stages=["scanner", "strategist", "risk_manager", "executor"],
        )
        json_str = result.model_dump_json()
        restored = PipelineResult.model_validate_json(json_str)
        assert len(restored.completed_stages) == 4
        assert restored.aborted_at is None

    def test_pipeline_result_aborted(self):
        """PipelineResult records early abort with None later stages."""
        result = PipelineResult(
            run_id="test-run-2",
            scanner_output=ScannerOutput(
                opportunities=[],
                symbols_scanned=5,
                reasoning="No opportunities found",
            ),
            completed_stages=["scanner"],
            aborted_at="scanner",
        )
        assert result.strategist_output is None
        assert result.risk_output is None
        assert result.executor_output is None
        assert result.aborted_at == "scanner"


# ============================================================================
# AgentConfig Tests
# ============================================================================


class TestAgentConfig:
    """Tests for agent configuration and model selection."""

    def test_default_model(self):
        """Default model is Claude Sonnet."""
        config = AgentConfig()
        assert config.model == "anthropic:claude-sonnet-4-6"

    def test_default_limits(self):
        """Default token and request limits are set."""
        config = AgentConfig()
        assert config.request_limit == 10
        assert config.response_tokens_limit == 4000
        assert config.max_tokens == 2000
        assert config.temperature == 0.1

    def test_get_model_uses_default(self):
        """get_model returns default model when no override."""
        config = AgentConfig()
        assert config.get_model("scanner") == "anthropic:claude-sonnet-4-6"
        assert config.get_model("strategist") == "anthropic:claude-sonnet-4-6"
        assert config.get_model("risk") == "anthropic:claude-sonnet-4-6"
        assert config.get_model("executor") == "anthropic:claude-sonnet-4-6"

    def test_get_model_with_override(self):
        """get_model returns agent-specific override when set."""
        config = AgentConfig(
            scanner_model="anthropic:claude-haiku-3",
            risk_model="anthropic:claude-opus-4",
        )
        assert config.get_model("scanner") == "anthropic:claude-haiku-3"
        assert config.get_model("strategist") == "anthropic:claude-sonnet-4-6"
        assert config.get_model("risk") == "anthropic:claude-opus-4"
        assert config.get_model("executor") == "anthropic:claude-sonnet-4-6"

    def test_get_model_unknown_agent_uses_default(self):
        """get_model with unknown agent name returns default model."""
        config = AgentConfig()
        assert config.get_model("unknown") == "anthropic:claude-sonnet-4-6"

    def test_checkpoint_conn_string_default(self):
        """Default checkpoint connection string uses psycopg format."""
        config = AgentConfig()
        assert "+asyncpg" not in config.checkpoint_conn_string
        assert config.checkpoint_conn_string.startswith("postgresql://")


# ============================================================================
# PipelineState Tests
# ============================================================================


class TestPipelineState:
    """Tests for LangGraph pipeline state."""

    def test_initial_state_structure(self):
        """PipelineState has all required keys with correct types."""
        state = make_pipeline_state()
        assert isinstance(state["watchlist"], list)
        assert isinstance(state["opportunities"], list)
        assert isinstance(state["trade_proposals"], list)
        assert isinstance(state["risk_assessments"], list)
        assert isinstance(state["execution_results"], list)
        assert isinstance(state["scanner_reasoning"], str)
        assert isinstance(state["run_id"], str)

    def test_state_json_serializable(self):
        """PipelineState can be serialized to JSON for checkpointing."""
        state = make_pipeline_state(
            opportunities=[make_opportunity().model_dump()],
            trade_proposals=[make_strategy_proposal().model_dump()],
        )
        json_str = json.dumps(state)
        restored = json.loads(json_str)
        assert len(restored["opportunities"]) == 1
        assert restored["opportunities"][0]["symbol"] == "SPY"

    def test_state_with_empty_lists(self):
        """PipelineState with empty lists is valid for pipeline start."""
        state = make_pipeline_state()
        assert len(state["opportunities"]) == 0
        assert state["aborted_at"] == ""


# ============================================================================
# Conditional Routing Tests
# ============================================================================


class TestRouting:
    """Tests for pipeline conditional routing functions."""

    def test_route_after_scan_with_opportunities(self):
        """route_after_scan routes to strategist when opportunities exist."""
        state = make_pipeline_state(
            opportunities=[make_opportunity().model_dump()]
        )
        assert route_after_scan(state) == "strategist"

    def test_route_after_scan_no_opportunities(self):
        """route_after_scan routes to END when no opportunities."""
        state = make_pipeline_state(opportunities=[])
        assert route_after_scan(state) == END

    def test_route_after_scan_empty_state(self):
        """route_after_scan routes to END with default empty state."""
        state = make_pipeline_state()
        assert route_after_scan(state) == END

    def test_route_after_risk_with_approvals(self):
        """route_after_risk routes to executor when approvals exist."""
        state = make_pipeline_state(
            risk_assessments=[make_risk_assessment(approved=True).model_dump()]
        )
        assert route_after_risk(state) == "executor"

    def test_route_after_risk_no_approvals(self):
        """route_after_risk routes to END when no approvals."""
        state = make_pipeline_state(
            risk_assessments=[make_risk_assessment(approved=False).model_dump()]
        )
        assert route_after_risk(state) == END

    def test_route_after_risk_empty(self):
        """route_after_risk routes to END with empty assessments."""
        state = make_pipeline_state(risk_assessments=[])
        assert route_after_risk(state) == END

    def test_route_after_risk_mixed_approvals(self):
        """route_after_risk routes to executor if ANY are approved."""
        state = make_pipeline_state(
            risk_assessments=[
                make_risk_assessment(approved=False).model_dump(),
                make_risk_assessment(approved=True).model_dump(),
            ]
        )
        assert route_after_risk(state) == "executor"


# ============================================================================
# Agent Definition Tests
# ============================================================================


class TestAgentDefinitions:
    """Tests that agent instances are properly defined with correct output types."""

    def test_scanner_agent_tools(self):
        """Scanner agent has the expected number of registered tools."""
        from trading.agents.scanner import scanner_agent

        # Scanner has 4 tools: get_iv_data, get_earnings_info,
        # get_market_snapshot, get_watchlist
        tool_names = list(scanner_agent._function_toolset.tools.keys())
        assert "get_iv_data" in tool_names
        assert "get_earnings_info" in tool_names
        assert "get_market_snapshot" in tool_names
        assert "get_watchlist" in tool_names
        assert len(tool_names) == 4

    def test_scanner_agent_output_type(self):
        """Scanner agent produces ScannerOutput."""
        from trading.agents.scanner import scanner_agent

        assert scanner_agent._output_type is ScannerOutput

    def test_strategist_agent_tools(self):
        """Strategist agent has the expected number of registered tools."""
        from trading.agents.strategist import strategist_agent

        tool_names = list(strategist_agent._function_toolset.tools.keys())
        assert "get_option_chain" in tool_names
        assert "get_current_price" in tool_names
        assert "get_risk_limits" in tool_names
        assert "get_opportunities" in tool_names
        assert len(tool_names) == 4

    def test_strategist_agent_output_type(self):
        """Strategist agent produces StrategistOutput."""
        from trading.agents.strategist import strategist_agent

        assert strategist_agent._output_type is StrategistOutput

    def test_risk_agent_tools(self):
        """Risk agent has the expected number of registered tools."""
        from trading.agents.risk_agent import risk_agent

        tool_names = list(risk_agent._function_toolset.tools.keys())
        assert "check_deterministic_risk" in tool_names
        assert "get_trade_proposals" in tool_names
        assert "get_contract_greeks" in tool_names
        assert len(tool_names) == 3

    def test_risk_agent_output_type(self):
        """Risk agent produces RiskManagerOutput."""
        from trading.agents.risk_agent import risk_agent

        assert risk_agent._output_type is RiskManagerOutput

    def test_executor_agent_tools(self):
        """Executor agent has the expected number of registered tools."""
        from trading.agents.executor_agent import executor_agent

        tool_names = list(executor_agent._function_toolset.tools.keys())
        assert "submit_trade" in tool_names
        assert "get_approved_trades" in tool_names
        assert len(tool_names) == 2

    def test_executor_agent_output_type(self):
        """Executor agent produces ExecutorOutput."""
        from trading.agents.executor_agent import executor_agent

        assert executor_agent._output_type is ExecutorOutput


# ============================================================================
# Decision Logging Tests
# ============================================================================


class TestDecisionLogging:
    """Tests for agent decision logging with mock session_factory."""

    def test_stage_order_mapping(self):
        """STAGE_ORDER maps all agents to correct ordinals."""
        assert STAGE_ORDER["regime_detector"] == 0
        assert STAGE_ORDER["scanner"] == 1
        assert STAGE_ORDER["strategist"] == 2
        assert STAGE_ORDER["risk_manager"] == 3
        assert STAGE_ORDER["executor"] == 4
        assert STAGE_ORDER["rolling_monitor"] == 5
        assert len(STAGE_ORDER) == 6

    def test_output_summary_scanner(self):
        """_get_output_summary produces correct summary for ScannerOutput."""
        output = ScannerOutput(
            opportunities=[make_opportunity()],
            symbols_scanned=5,
            reasoning="test",
        )
        summary = _get_output_summary(output)
        assert "1 opportunity found" in summary

    def test_output_summary_scanner_plural(self):
        """_get_output_summary uses plural for multiple opportunities."""
        output = ScannerOutput(
            opportunities=[make_opportunity(), make_opportunity(symbol="QQQ")],
            symbols_scanned=5,
            reasoning="test",
        )
        summary = _get_output_summary(output)
        assert "2 opportunities found" in summary

    def test_output_summary_strategist(self):
        """_get_output_summary produces correct summary for StrategistOutput."""
        output = StrategistOutput(
            proposals=[make_strategy_proposal()],
            reasoning="test",
        )
        summary = _get_output_summary(output)
        assert "1 proposal constructed" in summary

    def test_output_summary_risk_manager(self):
        """_get_output_summary produces correct summary for RiskManagerOutput."""
        output = RiskManagerOutput(
            assessments=[
                make_risk_assessment(approved=True),
                make_risk_assessment(proposal_id="test-2", approved=False),
            ],
            reasoning="test",
        )
        summary = _get_output_summary(output)
        assert "2 assessed" in summary
        assert "1 approved" in summary

    def test_output_summary_executor(self):
        """_get_output_summary produces correct summary for ExecutorOutput."""
        output = ExecutorOutput(
            results=[
                make_execution_result(status="submitted"),
                make_execution_result(proposal_id="test-2", status="failed"),
            ],
            reasoning="test",
        )
        summary = _get_output_summary(output)
        assert "2 results" in summary
        assert "1 submitted" in summary

    @pytest.mark.asyncio
    async def test_log_agent_decision_persists(self):
        """log_agent_decision persists record to DB via session_factory."""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.commit = AsyncMock()

        mock_factory = MagicMock()
        mock_factory.return_value = mock_session

        output = ScannerOutput(
            opportunities=[make_opportunity()],
            symbols_scanned=5,
            reasoning="Test scan reasoning",
        )

        from pydantic_ai.usage import Usage

        usage = Usage(input_tokens=100, output_tokens=200)

        await log_agent_decision(
            session_factory=mock_factory,
            run_id="test-run-123",
            agent_name="scanner",
            output=output,
            messages=[],
            usage=usage,
            duration_ms=500,
            input_summary="5 symbols: SPY, QQQ, IWM, AAPL, MSFT",
        )

        # Session was used (session.add was called)
        assert mock_session.add.called

    @pytest.mark.asyncio
    async def test_log_agent_decision_nonfatal_on_error(self):
        """log_agent_decision does not raise on DB errors (non-fatal)."""
        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(
            side_effect=RuntimeError("DB connection failed")
        )

        # Should NOT raise
        await log_agent_decision(
            session_factory=mock_factory,
            run_id="test-run-123",
            agent_name="scanner",
            error="some error",
        )

    @pytest.mark.asyncio
    async def test_log_agent_decision_with_error(self):
        """log_agent_decision persists error records without output."""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.commit = AsyncMock()

        mock_factory = MagicMock()
        mock_factory.return_value = mock_session

        await log_agent_decision(
            session_factory=mock_factory,
            run_id="test-run-456",
            agent_name="risk_manager",
            error="LLM API timeout",
            duration_ms=30000,
            input_summary="3 trade proposals from strategist",
        )

        assert mock_session.add.called


# ============================================================================
# Checkpoint Factory Tests
# ============================================================================


class TestCheckpointFactory:
    """Tests for the Postgres checkpoint factory."""

    @pytest.mark.asyncio
    async def test_rejects_asyncpg_connection_string(self):
        """create_checkpointer raises ValueError for asyncpg URLs."""
        from trading.agents.checkpoint import create_checkpointer

        with pytest.raises(ValueError, match="asyncpg"):
            await create_checkpointer(
                "postgresql+asyncpg://trading:trading@localhost:5432/trading"
            )

    def test_valid_conn_string_format(self):
        """Default AgentConfig checkpoint_conn_string is valid psycopg format."""
        config = AgentConfig()
        assert config.checkpoint_conn_string.startswith("postgresql://")
        assert "+asyncpg" not in config.checkpoint_conn_string


# ============================================================================
# Pipeline Factory and PipelineDeps Tests
# ============================================================================


class TestPipelineDeps:
    """Tests for PipelineDeps container and pipeline factory."""

    def test_pipeline_deps_creation(self):
        """PipelineDeps accepts all required dependencies."""
        deps = PipelineDeps(
            iv_engine=MagicMock(),
            earnings_calendar=MagicMock(),
            contract_resolver=MagicMock(),
            risk_manager=MagicMock(),
            execution_service=MagicMock(),
            redis_client=MagicMock(),
            session_factory=MagicMock(),
            settings=MagicMock(),
        )
        assert deps.iv_engine is not None
        assert deps.account_value == 100_000.0

    def test_pipeline_deps_custom_account_value(self):
        """PipelineDeps accepts custom account value."""
        deps = PipelineDeps(
            iv_engine=MagicMock(),
            earnings_calendar=MagicMock(),
            contract_resolver=MagicMock(),
            risk_manager=MagicMock(),
            execution_service=MagicMock(),
            redis_client=MagicMock(),
            session_factory=MagicMock(),
            settings=MagicMock(),
            account_value=250_000.0,
        )
        assert deps.account_value == 250_000.0

    @pytest.mark.asyncio
    async def test_create_pipeline_returns_compiled_graph(self):
        """create_pipeline returns a compiled StateGraph with nodes."""
        deps = PipelineDeps(
            iv_engine=MagicMock(),
            earnings_calendar=MagicMock(),
            contract_resolver=MagicMock(),
            risk_manager=MagicMock(),
            execution_service=MagicMock(),
            redis_client=MagicMock(),
            session_factory=MagicMock(),
            settings=MagicMock(),
        )
        graph = await create_pipeline(deps)
        # The compiled graph should have the expected nodes
        node_names = list(graph.nodes.keys())
        assert "scanner" in node_names
        assert "strategist" in node_names
        assert "risk_manager" in node_names
        assert "executor" in node_names

    @pytest.mark.asyncio
    async def test_create_pipeline_without_checkpointer(self):
        """create_pipeline works without a checkpointer."""
        deps = PipelineDeps(
            iv_engine=MagicMock(),
            earnings_calendar=MagicMock(),
            contract_resolver=MagicMock(),
            risk_manager=MagicMock(),
            execution_service=MagicMock(),
            redis_client=MagicMock(),
            session_factory=MagicMock(),
            settings=MagicMock(),
        )
        graph = await create_pipeline(deps, checkpointer=None)
        assert graph is not None


# ============================================================================
# App Wiring Tests
# ============================================================================


class TestAppWiring:
    """Tests that TradingApp.startup() creates Phase 5 pipeline components."""

    @pytest.mark.asyncio
    async def test_startup_creates_pipeline_deps(self, test_settings):
        """TradingApp.startup() initializes pipeline_deps."""
        from trading.app import TradingApp

        app = TradingApp(test_settings)
        await app.startup()

        assert app.pipeline_deps is not None
        assert isinstance(app.pipeline_deps, PipelineDeps)

    @pytest.mark.asyncio
    async def test_startup_pipeline_deps_has_services(self, test_settings):
        """PipelineDeps references Phase 2-4 services correctly."""
        from trading.app import TradingApp

        app = TradingApp(test_settings)
        await app.startup()

        assert app.pipeline_deps.iv_engine is app.iv_engine
        assert app.pipeline_deps.earnings_calendar is app.earnings_calendar
        assert app.pipeline_deps.risk_manager is app.risk_manager
        assert app.pipeline_deps.execution_service is app.execution_service
        assert app.pipeline_deps.redis_client is app.redis_client
        assert app.pipeline_deps.session_factory is app.session_factory
        assert app.pipeline_deps.settings is app.settings

    @pytest.mark.asyncio
    async def test_startup_agent_pipeline_not_compiled(self, test_settings):
        """agent_pipeline is None after startup (compiled in connect_ib)."""
        from trading.app import TradingApp

        app = TradingApp(test_settings)
        await app.startup()

        assert app.agent_pipeline is None

    @pytest.mark.asyncio
    async def test_init_pipeline_defaults(self, test_settings):
        """TradingApp.__init__ sets pipeline attributes to None."""
        from trading.app import TradingApp

        app = TradingApp(test_settings)
        assert app.pipeline_deps is None
        assert app.agent_pipeline is None
