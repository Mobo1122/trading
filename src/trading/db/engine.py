"""Async SQLAlchemy engine and session factory.

Provides factory functions for creating async database engines
and session factories for use throughout the application.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)


def create_db_engine(
    database_url: str,
    pool_size: int = 10,
    pool_overflow: int = 5,
) -> AsyncEngine:
    """Create an async SQLAlchemy engine.

    Args:
        database_url: Database connection URL (postgresql+asyncpg://...).
        pool_size: Number of persistent connections in the pool.
        pool_overflow: Max additional connections beyond pool_size.

    Returns:
        Configured AsyncEngine instance.
    """
    return create_async_engine(
        database_url,
        pool_size=pool_size,
        max_overflow=pool_overflow,
        pool_pre_ping=True,
        echo=False,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    """Create an async session factory bound to the given engine.

    Sessions created by this factory have expire_on_commit=False,
    allowing attribute access after commit without re-querying.

    Args:
        engine: The AsyncEngine to bind sessions to.

    Returns:
        Configured async_sessionmaker instance.
    """
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )
