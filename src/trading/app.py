"""Application entrypoint for the trading system.

Provides the TradingApp class and main() function for starting the system.
Configures structured logging, displays a startup banner, and wires all
Phase 1 components: IB connection, database, Redis, order tracking,
health monitoring, and the emergency kill switch.
"""

from __future__ import annotations

import asyncio
import re

import structlog

from trading.cache.redis import close_redis_client, create_redis_client
from trading.config import Settings
from trading.core.connection import IBConnectionManager
from trading.core.health import HealthMonitor
from trading.db.engine import create_db_engine, create_session_factory
from trading.kill_switch import KillSwitch
from trading.orders.tracker import OrderTracker


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

    Wires all Phase 1 components together and manages their lifecycle:
      - IB connection manager (with auto-reconnect)
      - Database engine and session factory
      - Redis client
      - Order tracker
      - Kill switch (emergency shutdown)
      - Health monitor (IB + DB + Redis health checks)
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.log = structlog.get_logger("trading.app")
        self.connection_manager: IBConnectionManager | None = None
        self.db_engine = None
        self.session_factory = None
        self.redis_client = None
        self.health_monitor: HealthMonitor | None = None
        self.kill_switch: KillSwitch | None = None
        self.order_tracker: OrderTracker | None = None

    async def startup(self) -> None:
        """Start the trading application.

        Configures logging, prints startup banner, and creates all
        Phase 1 components. Does NOT connect to IB -- call connect_ib()
        separately (allows testing without a running IB Gateway).
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

        # Create database engine and session factory
        self.db_engine = create_db_engine(
            self.settings.database.url,
            pool_size=self.settings.database.pool_size,
            pool_overflow=self.settings.database.pool_overflow,
        )
        self.session_factory = create_session_factory(self.db_engine)

        # Create Redis client
        self.redis_client = create_redis_client(self.settings.redis.url)

        # Create IB connection manager (connect later via connect_ib)
        self.connection_manager = IBConnectionManager(self.settings)

        # Create order tracker
        self.order_tracker = OrderTracker(self.session_factory)

        # Create kill switch
        self.kill_switch = KillSwitch(self.connection_manager.ib)

        # Create health monitor
        self.health_monitor = HealthMonitor(
            connection_manager=self.connection_manager,
            db_engine=self.db_engine,
            redis_client=self.redis_client,
            settings=self.settings,
        )

        self.log.info("startup.complete")

    async def connect_ib(self) -> None:
        """Connect to IB Gateway.

        Separated from startup() to allow testing without IB Gateway.
        Must call startup() first.
        """
        if self.connection_manager is None:
            raise RuntimeError("Must call startup() before connect_ib()")
        await self.connection_manager.connect()

    async def shutdown(self) -> None:
        """Shut down the trading application.

        Disconnects IB, closes Redis, and disposes the database engine.
        Each step is wrapped in try/except to ensure all cleanup runs
        even if individual steps fail.
        """
        self.log.info("shutdown.starting")

        if self.connection_manager is not None:
            try:
                await self.connection_manager.disconnect()
            except Exception:
                self.log.warning("shutdown.ib_disconnect_failed", exc_info=True)

        if self.redis_client is not None:
            try:
                await close_redis_client(self.redis_client)
            except Exception:
                self.log.warning("shutdown.redis_close_failed", exc_info=True)

        if self.db_engine is not None:
            try:
                await self.db_engine.dispose()
            except Exception:
                self.log.warning("shutdown.db_dispose_failed", exc_info=True)

        self.log.info("shutdown", status="complete")


async def main() -> None:
    """Load settings, create the application, and run the main loop.

    Handles keyboard interrupt for graceful shutdown.
    """
    settings = Settings()
    app = TradingApp(settings)
    await app.startup()
    try:
        await app.connect_ib()
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
