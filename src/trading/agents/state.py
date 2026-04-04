"""LangGraph pipeline state definition.

Defines the shared TypedDict that flows through the agent pipeline graph.
Each LangGraph node reads from and writes to this state.

All fields use JSON-serializable types (``list[dict]`` instead of Pydantic
models) because LangGraph TypedDict state must be serializable for
checkpoint persistence. Agents convert between Pydantic models and dicts
at node boundaries using ``model.model_dump()`` / ``Model(**dict_data)``.
"""

from __future__ import annotations

from typing import TypedDict


class PipelineState(TypedDict):
    """Shared state flowing through the agent pipeline.

    Attributes:
        watchlist: Symbols to scan for opportunities.
        opportunities: Serialized Opportunity dicts from scanner.
        trade_proposals: Serialized StrategyProposal dicts from strategist.
        risk_assessments: Serialized RiskAssessment dicts from risk manager.
        execution_results: Serialized ExecutionResult dicts from executor.
        scanner_reasoning: Scanner agent's overall reasoning summary.
        strategist_reasoning: Strategist agent's overall reasoning summary.
        risk_reasoning: Risk manager agent's overall reasoning summary.
        executor_reasoning: Executor agent's overall reasoning summary.
        run_id: Unique identifier for this pipeline run.
        aborted_at: Stage name where pipeline stopped early (empty if not).
        regime_classification: Serialized RegimeClassification dict from
            regime detector (see ``trading.agents.regime``).
        rolling_candidates: Serialized candidate dicts accumulated across
            rolling pipeline runs for downstream agents.
        rolling_decisions: Serialized decision dicts accumulated across
            rolling pipeline runs for downstream agents.
    """

    watchlist: list[str]
    opportunities: list[dict]
    trade_proposals: list[dict]
    risk_assessments: list[dict]
    execution_results: list[dict]
    scanner_reasoning: str
    strategist_reasoning: str
    risk_reasoning: str
    executor_reasoning: str
    run_id: str
    aborted_at: str
    regime_classification: dict
    rolling_candidates: list[dict]
    rolling_decisions: list[dict]
