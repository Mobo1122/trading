"""LangGraph Postgres checkpoint factory.

Creates an AsyncPostgresSaver for durable pipeline state persistence.
The checkpointer uses psycopg (NOT asyncpg) to connect to PostgreSQL,
keeping it isolated from the SQLAlchemy/asyncpg driver used by the
rest of the application. See RESEARCH.md Pitfall 1.

Usage::

    checkpointer, pool = await create_checkpointer(conn_string)
    graph = workflow.compile(checkpointer=checkpointer)
    # on shutdown:
    await pool.close()
"""

from __future__ import annotations

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool


async def create_checkpointer(
    conn_string: str,
) -> tuple[AsyncPostgresSaver, AsyncConnectionPool]:
    """Create and initialize a Postgres checkpoint saver.

    Connects to PostgreSQL using psycopg and creates the internal
    checkpoint tables if they do not already exist.

    Args:
        conn_string: PostgreSQL connection string in psycopg format
            (``postgresql://user:pass@host:port/db``). Must NOT use
            the asyncpg dialect (``postgresql+asyncpg://``).

    Returns:
        Tuple of (checkpointer, pool). The caller owns the pool and
        must call ``await pool.close()`` during shutdown.

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

    # autocommit=True is required by AsyncPostgresSaver for CREATE TABLE
    pool = AsyncConnectionPool(
        conninfo=conn_string,
        min_size=1,
        max_size=4,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0},
    )
    await pool.open()
    checkpointer = AsyncPostgresSaver(conn=pool)
    await checkpointer.setup()
    return checkpointer, pool
