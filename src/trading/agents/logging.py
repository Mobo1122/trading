"""Agent decision logging with full reasoning chain DB persistence.

Every agent run in the pipeline is logged to the ``agent_decision_log``
table with:
  - Full message history (serialized JSON) for audit replay.
  - Structured output (JSON) for programmatic analysis.
  - Reasoning text for human-readable explanations.
  - Token usage for cost tracking.
  - Duration for performance monitoring.

Logging is **non-fatal**: failures are caught and warned via structlog
so a logging error never crashes the pipeline.

Exports:
    STAGE_ORDER: Mapping of agent names to pipeline stage numbers.
    log_agent_decision: Async function to persist a decision record.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from pydantic import BaseModel
from pydantic_ai.usage import Usage
from pydantic_core import to_jsonable_python

from trading.db.models import AgentDecisionLog
from trading.db.session import get_session

log = structlog.get_logger("trading.agents.logging")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STAGE_ORDER: dict[str, int] = {
    "regime_detector": 0,
    "scanner": 1,
    "strategist": 2,
    "risk_manager": 3,
    "executor": 4,
    "rolling_monitor": 5,
}
"""Mapping of agent names to their ordinal position in the pipeline.

``regime_detector`` (stage 0) runs before scanner to classify market
conditions. ``rolling_monitor`` (stage 5) logs rolling evaluation
decisions after executor completes.
"""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_output_summary(output: BaseModel) -> str:
    """Build a concise human-readable summary of an agent output.

    Inspects well-known fields on the various output models
    (``opportunities``, ``proposals``, ``assessments``, ``results``)
    to produce a one-line summary string suitable for the
    ``output_summary`` column.

    Args:
        output: A Pydantic model produced by one of the pipeline agents.

    Returns:
        A short summary string, e.g.
        ``"3 opportunities found"`` or ``"2 proposals constructed"``.
    """
    # RegimeClassification
    if hasattr(output, "regime"):
        return f"regime: {output.regime}"

    # ScannerOutput
    if hasattr(output, "opportunities"):
        n = len(output.opportunities)
        return f"{n} opportunit{'y' if n == 1 else 'ies'} found"

    # StrategistOutput
    if hasattr(output, "proposals"):
        n = len(output.proposals)
        return f"{n} proposal{'s' if n != 1 else ''} constructed"

    # RiskManagerOutput
    if hasattr(output, "assessments"):
        assessments = output.assessments
        n = len(assessments)
        approved = sum(1 for a in assessments if getattr(a, "approved", False))
        return f"{n} assessed, {approved} approved"

    # ExecutorOutput
    if hasattr(output, "results"):
        results = output.results
        n = len(results)
        submitted = sum(
            1 for r in results if getattr(r, "status", "") == "submitted"
        )
        return f"{n} result{'s' if n != 1 else ''}, {submitted} submitted"

    return "output logged"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def log_agent_decision(
    session_factory: Any,
    run_id: str,
    agent_name: str,
    output: BaseModel | None = None,
    messages: list | None = None,
    usage: Usage | None = None,
    duration_ms: int | None = None,
    error: str | None = None,
    input_summary: str | None = None,
) -> None:
    """Persist an agent decision record to the database.

    The entire function is wrapped in a try/except so a logging failure
    never propagates to the caller.  This matches the project-wide
    pattern of non-fatal persistence errors (see 03-05, 04-03).

    Args:
        session_factory: SQLAlchemy ``async_sessionmaker`` for DB access.
        run_id: Pipeline run identifier (UUID string).
        agent_name: Agent name (one of the STAGE_ORDER keys).
        output: Validated Pydantic output model from the agent run.
            ``None`` when logging an error before output was produced.
        messages: Full PydanticAI message history from
            ``result.all_messages()``.
        usage: PydanticAI ``Usage`` object with token counts.
        duration_ms: Wall-clock duration of the agent run in milliseconds.
        error: Error message string if the agent run failed.
        input_summary: Human-readable description of what the agent
            received as input (e.g. ``"5 symbols: SPY, QQQ, ..."``)
    """
    try:
        # Serialize messages
        messages_json: str | None = None
        if messages is not None:
            try:
                messages_json = json.dumps(to_jsonable_python(messages))
            except Exception:
                log.warning(
                    "agent_logging.messages_serialize_failed",
                    agent=agent_name,
                    run_id=run_id,
                )
                messages_json = None

        # Serialize output
        output_json: str | None = None
        output_summary: str | None = None
        reasoning: str | None = None
        if output is not None:
            try:
                output_json = output.model_dump_json()
            except Exception:
                log.warning(
                    "agent_logging.output_serialize_failed",
                    agent=agent_name,
                    run_id=run_id,
                )

            output_summary = _get_output_summary(output)

            if hasattr(output, "reasoning"):
                reasoning = output.reasoning

        # Extract token counts
        request_tokens: int | None = None
        response_tokens: int | None = None
        if usage is not None:
            request_tokens = usage.request_tokens or None
            response_tokens = usage.response_tokens or None

        stage = STAGE_ORDER.get(agent_name, 0)

        record = AgentDecisionLog(
            run_id=run_id,
            agent_name=agent_name,
            stage_order=stage,
            input_summary=input_summary,
            output_summary=output_summary,
            reasoning=reasoning,
            messages_json=messages_json,
            output_json=output_json,
            request_tokens=request_tokens,
            response_tokens=response_tokens,
            model_name=None,  # not available from Usage object
            duration_ms=duration_ms,
            error=error,
        )

        async with get_session(session_factory) as session:
            session.add(record)

        log.info(
            "agent_logging.persisted",
            run_id=run_id,
            agent=agent_name,
            stage=stage,
            duration_ms=duration_ms,
            request_tokens=request_tokens,
            response_tokens=response_tokens,
            error=error is not None,
            output_summary=output_summary,
        )

    except Exception:
        # Non-fatal: log warning and continue
        log.warning(
            "agent_logging.persist_failed",
            run_id=run_id,
            agent=agent_name,
            exc_info=True,
        )
