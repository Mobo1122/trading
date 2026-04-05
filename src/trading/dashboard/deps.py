"""Shared FastAPI dependencies for dashboard route handlers.

Extracted from server.py to avoid circular imports when route modules
need to import dependencies that server.py also defines.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session.

    Uses the session factory stored on app.state during lifespan startup.
    Commits on success, rolls back on exception.

    Yields:
        An AsyncSession for database operations.
    """
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
