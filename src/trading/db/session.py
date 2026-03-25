"""Async session context manager for database operations.

Provides a session scope that automatically commits on success
and rolls back on exception, ensuring clean transaction boundaries.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@asynccontextmanager
async def get_session(
    session_factory: async_sessionmaker,
) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session with automatic transaction management.

    Commits the session on successful exit. Rolls back on any exception,
    then re-raises the exception for upstream handling.

    Args:
        session_factory: An async_sessionmaker instance to create sessions from.

    Yields:
        An AsyncSession for database operations.

    Raises:
        Exception: Re-raises any exception after rollback.
    """
    session = session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
