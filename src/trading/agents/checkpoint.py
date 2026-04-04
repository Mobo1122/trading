"""LangGraph Postgres checkpoint factory.

Creates an AsyncPostgresSaver for durable pipeline state persistence.
The checkpointer uses psycopg (NOT asyncpg) to connect to PostgreSQL,
keeping it isolated from the SQLAlchemy/asyncpg driver used by the
rest of the application. See RESEARCH.md Pitfall 1.

Usage::

    checkpointer = await create_checkpointer(conn_string)
    graph = workflow.compile(checkpointer=checkpointer)
"""

from __future__ import annotations

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


async def create_checkpointer(conn_string: str) -> AsyncPostgresSaver:
    """Create and initialize a Postgres checkpoint saver.

    Connects to PostgreSQL using psycopg and creates the internal
    checkpoint tables if they do not already exist.

    Args:
        conn_string: PostgreSQL connection string in psycopg format
            (``postgresql://user:pass@host:port/db``). Must NOT use
            the asyncpg dialect (``postgresql+asyncpg://``).

    Returns:
        An initialized AsyncPostgresSaver ready for use with
        ``workflow.compile(checkpointer=...)``.

    Raises:
        ValueError: If the connection string contains ``+asyncpg``,
            which is incompatible with the psycopg-based checkpointer.
    """
    if "+asyncpg" in conn_string:
        raise ValueError(
            "Checkpoint connection string must use psycopg format "
            "(postgresql://...), not asyncpg "
            "(postgresql+asyncpg://...). "
            "See RESEARCH.md Pitfall 1."
        )

    checkpointer = AsyncPostgresSaver.from_conn_string(conn_string)
    await checkpointer.setup()
    return checkpointer
