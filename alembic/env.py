"""Alembic environment configuration for async migrations.

Loads the database URL from the trading config system so that
migrations use the same connection settings as the application.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from trading.config import Settings
from trading.db.models import Base

# Alembic Config object -- provides access to .ini file values.
config = context.config

# Set up Python logging from the config file.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Load database URL from application settings and override the ini placeholder.
settings = Settings()
config.set_main_option("sqlalchemy.url", settings.database.url)

# Model metadata for autogenerate support.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Configures the context with just a URL (no Engine needed),
    so a DBAPI doesn't need to be available.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations within a synchronous connection context."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations.

    Uses NullPool because migrations are short-lived operations
    that don't benefit from connection pooling.
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode with async engine."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
