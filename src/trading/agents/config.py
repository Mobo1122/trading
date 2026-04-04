"""Agent configuration for the trading pipeline.

Defines per-agent model selection, temperature, token limits, and
checkpoint connection string. Integrates into the main Settings class
via the ``agents`` field.

Each agent can override the default model by setting its specific field
(e.g., ``scanner_model``). If not set, the agent falls back to the
shared ``model`` default.

The checkpoint connection string MUST use psycopg format
(``postgresql://``), NOT asyncpg (``postgresql+asyncpg://``).
See RESEARCH.md Pitfall 1 for details.
"""

from __future__ import annotations

from pydantic import BaseModel


class AgentConfig(BaseModel):
    """Configuration for the AI agent pipeline.

    Attributes:
        model: Default LLM model for all agents (PydanticAI model string).
        scanner_model: Override model for the scanner agent.
        strategist_model: Override model for the strategist agent.
        risk_model: Override model for the risk manager agent.
        executor_model: Override model for the executor agent.
        temperature: LLM sampling temperature (low for consistent outputs).
        max_tokens: Maximum tokens per LLM response.
        request_limit: PydanticAI UsageLimits.request_limit per agent run.
        response_tokens_limit: PydanticAI UsageLimits.response_tokens_limit.
        checkpoint_conn_string: psycopg connection string for LangGraph
            checkpoint persistence. Must NOT contain ``+asyncpg``.
    """

    model: str = "anthropic:claude-sonnet-4-6"
    scanner_model: str | None = None
    strategist_model: str | None = None
    risk_model: str | None = None
    executor_model: str | None = None
    temperature: float = 0.1
    max_tokens: int = 2000
    request_limit: int = 10
    response_tokens_limit: int = 4000
    checkpoint_conn_string: str = (
        "postgresql://trading:trading@localhost:5432/trading"
    )

    def get_model(self, agent_name: str) -> str:
        """Return the model for a specific agent, falling back to default.

        Args:
            agent_name: One of "scanner", "strategist", "risk", "executor".

        Returns:
            The agent-specific model override if set, otherwise the default
            ``model`` value.
        """
        override_map = {
            "scanner": self.scanner_model,
            "strategist": self.strategist_model,
            "risk": self.risk_model,
            "executor": self.executor_model,
        }
        override = override_map.get(agent_name)
        return override if override is not None else self.model
