"""Unit tests for pipeline approval gate, threshold routing, and background execution.

Tests the three-way routing after risk_manager (executor / approval_gate / END),
the _exceeds_threshold helper, and the _await_approval_and_execute background
task for approved, rejected, and timed_out paths.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.graph import END

from trading.agents.pipeline import (
    PipelineDeps,
    _await_approval_and_execute,
    _exceeds_threshold,
    _make_route_after_risk,
)
from trading.alerts.config import AutoExecuteThresholds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_thresholds(
    max_loss: float = 500.0,
    max_delta: float = 50.0,
    max_vega: float = 100.0,
) -> AutoExecuteThresholds:
    return AutoExecuteThresholds(
        max_loss_dollars=max_loss,
        max_delta_impact=max_delta,
        max_vega_impact=max_vega,
    )


def _make_deps(
    approval_manager: Any = None,
    thresholds: AutoExecuteThresholds | None = None,
    redis_client: Any = None,
) -> MagicMock:
    """Create a mock PipelineDeps with approval-related fields."""
    deps = MagicMock(spec=PipelineDeps)
    deps.approval_manager = approval_manager
    deps.auto_execute_thresholds = thresholds
    deps.redis_client = redis_client
    deps.execution_service = MagicMock()
    deps.session_factory = MagicMock()
    deps.settings = MagicMock()
    deps.settings.trading.mode = "paper"
    return deps


def _make_state(
    approved_assessments: list[dict] | None = None,
    trade_proposals: list[dict] | None = None,
    run_id: str = "test-run-123",
) -> dict:
    """Create a minimal pipeline state dict."""
    return {
        "watchlist": ["SPY"],
        "opportunities": [],
        "trade_proposals": trade_proposals or [],
        "risk_assessments": approved_assessments or [],
        "execution_results": [],
        "scanner_reasoning": "",
        "strategist_reasoning": "",
        "risk_reasoning": "",
        "executor_reasoning": "",
        "run_id": run_id,
        "aborted_at": "",
        "regime_classification": {},
        "rolling_candidates": [],
        "rolling_decisions": [],
        "approval_status": "",
        "approval_id": "",
    }


# ---------------------------------------------------------------------------
# _exceeds_threshold tests
# ---------------------------------------------------------------------------


class TestExceedsThreshold:
    """Tests for the _exceeds_threshold helper."""

    def test_exceeds_max_loss(self):
        thresholds = _make_thresholds(max_loss=500.0)
        assessment = {"proposal_id": "p1", "symbol": "SPY"}
        proposals = [{"proposal_id": "p1", "max_loss": -600}]
        assert _exceeds_threshold(assessment, proposals, thresholds) is True

    def test_exceeds_delta(self):
        thresholds = _make_thresholds(max_delta=50.0)
        assessment = {"proposal_id": "p1", "symbol": "SPY"}
        proposals = [
            {"proposal_id": "p1", "max_loss": 100, "delta_impact": 75}
        ]
        assert _exceeds_threshold(assessment, proposals, thresholds) is True

    def test_exceeds_vega(self):
        thresholds = _make_thresholds(max_vega=100.0)
        assessment = {"proposal_id": "p1", "symbol": "SPY"}
        proposals = [
            {
                "proposal_id": "p1",
                "max_loss": 100,
                "delta_impact": 10,
                "vega_impact": 150,
            }
        ]
        assert _exceeds_threshold(assessment, proposals, thresholds) is True

    def test_proposal_not_found_returns_true(self):
        """Safe default: require approval if proposal cannot be found."""
        thresholds = _make_thresholds()
        assessment = {"proposal_id": "unknown", "symbol": "???"}
        proposals = [{"proposal_id": "p1", "symbol": "SPY"}]
        assert _exceeds_threshold(assessment, proposals, thresholds) is True

    def test_within_all_thresholds(self):
        thresholds = _make_thresholds(
            max_loss=500.0, max_delta=50.0, max_vega=100.0
        )
        assessment = {"proposal_id": "p1", "symbol": "SPY"}
        proposals = [
            {
                "proposal_id": "p1",
                "max_loss": -200,
                "delta_impact": 20,
                "vega_impact": 50,
            }
        ]
        assert _exceeds_threshold(assessment, proposals, thresholds) is False

    def test_matches_by_symbol_fallback(self):
        """Falls back to symbol matching when proposal_id doesn't match."""
        thresholds = _make_thresholds(max_loss=500.0)
        assessment = {"proposal_id": "", "symbol": "SPY"}
        proposals = [{"proposal_id": "p1", "symbol": "SPY", "max_loss": -600}]
        assert _exceeds_threshold(assessment, proposals, thresholds) is True


# ---------------------------------------------------------------------------
# Route function tests
# ---------------------------------------------------------------------------


class TestRouteAfterRisk:
    """Tests for the three-way routing function."""

    def test_returns_end_when_no_approved(self):
        deps = _make_deps(
            approval_manager=MagicMock(),
            thresholds=_make_thresholds(),
        )
        route = _make_route_after_risk(deps)
        state = _make_state(
            approved_assessments=[{"approved": False}],
        )
        assert route(state) == END

    def test_returns_executor_when_no_approval_manager(self):
        """Backward compatible: no approval gate configured."""
        deps = _make_deps(
            approval_manager=None,
            thresholds=_make_thresholds(),
        )
        route = _make_route_after_risk(deps)
        state = _make_state(
            approved_assessments=[{"approved": True, "symbol": "SPY"}],
        )
        assert route(state) == "executor"

    def test_returns_executor_when_no_thresholds(self):
        """Backward compatible: no thresholds configured."""
        deps = _make_deps(
            approval_manager=MagicMock(),
            thresholds=None,
        )
        route = _make_route_after_risk(deps)
        state = _make_state(
            approved_assessments=[{"approved": True, "symbol": "SPY"}],
        )
        assert route(state) == "executor"

    def test_returns_executor_when_below_threshold(self):
        deps = _make_deps(
            approval_manager=MagicMock(),
            thresholds=_make_thresholds(max_loss=1000.0),
        )
        route = _make_route_after_risk(deps)
        state = _make_state(
            approved_assessments=[
                {"approved": True, "proposal_id": "p1", "symbol": "SPY"}
            ],
            trade_proposals=[
                {
                    "proposal_id": "p1",
                    "max_loss": -200,
                    "delta_impact": 10,
                    "vega_impact": 30,
                }
            ],
        )
        assert route(state) == "executor"

    def test_returns_approval_gate_when_above_threshold(self):
        deps = _make_deps(
            approval_manager=MagicMock(),
            thresholds=_make_thresholds(max_loss=100.0),
        )
        route = _make_route_after_risk(deps)
        state = _make_state(
            approved_assessments=[
                {"approved": True, "proposal_id": "p1", "symbol": "SPY"}
            ],
            trade_proposals=[
                {
                    "proposal_id": "p1",
                    "max_loss": -500,
                    "delta_impact": 10,
                    "vega_impact": 30,
                }
            ],
        )
        assert route(state) == "approval_gate"

    def test_any_exceeds_triggers_approval(self):
        """If ANY approved assessment exceeds, route to approval_gate."""
        deps = _make_deps(
            approval_manager=MagicMock(),
            thresholds=_make_thresholds(max_loss=500.0),
        )
        route = _make_route_after_risk(deps)
        state = _make_state(
            approved_assessments=[
                {"approved": True, "proposal_id": "p1", "symbol": "SPY"},
                {"approved": True, "proposal_id": "p2", "symbol": "QQQ"},
            ],
            trade_proposals=[
                {
                    "proposal_id": "p1",
                    "max_loss": -100,
                    "delta_impact": 5,
                    "vega_impact": 10,
                },
                {
                    "proposal_id": "p2",
                    "max_loss": -800,
                    "delta_impact": 5,
                    "vega_impact": 10,
                },
            ],
        )
        assert route(state) == "approval_gate"


# ---------------------------------------------------------------------------
# _await_approval_and_execute tests
# ---------------------------------------------------------------------------


class TestAwaitApprovalAndExecute:
    """Tests for the background approval -> execution task."""

    @pytest.mark.asyncio
    async def test_approved_calls_executor(self):
        """When approved, should call _executor_node."""
        mock_manager = AsyncMock()
        mock_manager.request_approval.return_value = "approved"
        mock_redis = AsyncMock()

        deps = _make_deps(
            approval_manager=mock_manager,
            redis_client=mock_redis,
        )
        state = _make_state(
            approved_assessments=[
                {"approved": True, "proposal_id": "p1"}
            ],
        )

        with patch(
            "trading.agents.pipeline._executor_node",
            new_callable=AsyncMock,
        ) as mock_exec:
            await _await_approval_and_execute(
                "approval-123", {"symbols": ["SPY"]}, state, deps
            )
            mock_exec.assert_awaited_once_with(state, deps)

        # Verify _await_approval_and_execute does NOT directly publish
        # alerts:trade_executed (that comes from _executor_node only)
        for call in mock_redis.publish.call_args_list:
            channel = call[0][0]
            assert channel != "alerts:trade_executed", (
                "_await_approval_and_execute should not publish "
                "alerts:trade_executed directly"
            )

    @pytest.mark.asyncio
    async def test_rejected_does_not_call_executor(self):
        """When rejected, should NOT call _executor_node."""
        mock_manager = AsyncMock()
        mock_manager.request_approval.return_value = "rejected"
        mock_redis = AsyncMock()

        deps = _make_deps(
            approval_manager=mock_manager,
            redis_client=mock_redis,
        )
        state = _make_state()

        with patch(
            "trading.agents.pipeline._executor_node",
            new_callable=AsyncMock,
        ) as mock_exec:
            await _await_approval_and_execute(
                "approval-123",
                {"symbols": ["SPY"], "run_id": "test"},
                state,
                deps,
            )
            mock_exec.assert_not_awaited()

        # Should publish alerts:trade_rejected
        mock_redis.publish.assert_awaited_once()
        call_args = mock_redis.publish.call_args[0]
        assert call_args[0] == "alerts:trade_rejected"

    @pytest.mark.asyncio
    async def test_timed_out_does_not_call_executor(self):
        """When timed out, should NOT call _executor_node."""
        mock_manager = AsyncMock()
        mock_manager.request_approval.return_value = "timed_out"
        mock_redis = AsyncMock()

        deps = _make_deps(
            approval_manager=mock_manager,
            redis_client=mock_redis,
        )
        state = _make_state()

        with patch(
            "trading.agents.pipeline._executor_node",
            new_callable=AsyncMock,
        ) as mock_exec:
            await _await_approval_and_execute(
                "approval-456",
                {"symbols": ["QQQ"], "run_id": "test"},
                state,
                deps,
            )
            mock_exec.assert_not_awaited()

        # Should publish alerts:trade_rejected
        mock_redis.publish.assert_awaited_once()
        call_args = mock_redis.publish.call_args[0]
        assert call_args[0] == "alerts:trade_rejected"

    @pytest.mark.asyncio
    async def test_error_does_not_crash(self):
        """Errors in background task should be caught, not raised."""
        mock_manager = AsyncMock()
        mock_manager.request_approval.side_effect = RuntimeError("boom")

        deps = _make_deps(approval_manager=mock_manager)
        state = _make_state()

        # Should not raise
        await _await_approval_and_execute(
            "approval-789", {"symbols": ["SPY"]}, state, deps
        )
