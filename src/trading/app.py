"""Application entrypoint for the trading system.

Provides the TradingApp class and main() function for starting the system.
Configures structured logging and displays a startup banner showing the
active trading mode and connection parameters.
"""

from __future__ import annotations

import asyncio
import re

import structlog

from trading.config import Settings


def setup_logging(settings: Settings) -> None:
    """Configure structlog based on application settings.

    Args:
        settings: Application settings with logging configuration.
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.logging.format == "json":
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.UnicodeDecoder(),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            structlog._log_levels.NAME_TO_LEVEL.get(
                settings.logging.level.lower(), 20  # default to INFO
            )
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _mask_password(url: str) -> str:
    """Mask password in a database/redis URL for safe logging.

    Replaces the password portion of URLs like:
      postgresql+asyncpg://user:secret@host/db
    with:
      postgresql+asyncpg://user:***@host/db
    """
    return re.sub(r"(://[^:]+:)[^@]+(@)", r"\1***\2", url)


class TradingApp:
    """Main trading application lifecycle manager.

    Handles startup logging and banner display. Future plans will
    add connection management, order processing, and shutdown logic.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.log = structlog.get_logger("trading.app")

    async def startup(self) -> None:
        """Start the trading application.

        Configures logging, prints startup banner with trading mode
        and connection parameters.
        """
        setup_logging(self.settings)

        # Re-bind logger after structlog is configured
        self.log = structlog.get_logger("trading.app")

        mode = self.settings.trading.mode.upper()
        port = self.settings.trading.ib_port
        db_url = _mask_password(self.settings.database.url)
        redis_url = self.settings.redis.url

        # Always log banner at warning level so it shows regardless of log config
        self.log.warning(
            "startup_banner",
            trading_mode=mode,
            ib_host=self.settings.ib.host,
            ib_port=port,
            database_url=db_url,
            redis_url=redis_url,
        )

        if self.settings.trading.mode == "live":
            self.log.warning("LIVE TRADING MODE ACTIVE")
        else:
            self.log.info("Paper trading mode (safe)")

    async def shutdown(self) -> None:
        """Shut down the trading application.

        Placeholder for future cleanup: close IB connection,
        drain order queues, close database pool, etc.
        """
        self.log.info("shutdown", status="complete")


async def main() -> None:
    """Load settings, create the application, and run startup."""
    settings = Settings()
    app = TradingApp(settings)
    await app.startup()


if __name__ == "__main__":
    asyncio.run(main())
