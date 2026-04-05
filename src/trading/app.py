"""Application entrypoint for the trading system.

Provides the TradingApp class and main() function for starting the system.
Configures structured logging, displays a startup banner, and wires all
Phase 1-8 components: IB connection, database, Redis, order tracking,
health monitoring, kill switch, market data streaming, IV analytics,
earnings calendar, risk engine, order execution pipeline, agent pipeline,
regime detection, option position rolling, dashboard publisher, alert
routing, and approval management.
"""

from __future__ import annotations

import asyncio
import re

import structlog

from trading.agents.checkpoint import create_checkpointer
from trading.agents.pipeline import PipelineDeps, create_pipeline, run_pipeline
from trading.agents.regime import RegimeDetector
from trading.agents.rolling import ExpirationMonitor
from trading.analytics.earnings import EarningsCalendar
from trading.analytics.iv_engine import IVEngine
from trading.analytics.iv_history import IVHistoryManager
from trading.cache.redis import close_redis_client, create_redis_client
from trading.config import Settings
from trading.contracts import ContractCache, ContractResolver
from trading.core.connection import IBConnectionManager
from trading.core.health import HealthMonitor
from trading.dashboard.publisher import DashboardPublisher
from trading.db.engine import create_db_engine, create_session_factory
from trading.kill_switch import KillSwitch
from trading.market_data.distributor import RedisDistributor
from trading.market_data.manager import MarketDataManager
from trading.market_data.staleness import StalenessMonitor
from trading.market_data.subscriber import SubscriptionManager
from trading.market_data.writer import TimescaleDBWriter
from trading.orders.execution_service import OrderExecutionService
from trading.orders.fill_tracker import FillTracker
from trading.orders.recovery import OrderRecoveryManager
from trading.orders.tracker import OrderTracker
from trading.alerts.approval import ApprovalManager
from trading.alerts.router import AlertRouter
from trading.alerts.slack import SlackNotifier
from trading.alerts.sms import SMSNotifier
from trading.risk.circuit_breaker import CircuitBreaker
from trading.risk.manager import RiskManager
from trading.risk.repository import RiskRepository


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

    Wires all Phase 1-8 components together and manages their lifecycle:
      - IB connection manager (with auto-reconnect)
      - Database engine and session factory
      - Redis client
      - Order tracker
      - Kill switch (emergency shutdown)
      - Health monitor (IB + DB + Redis health checks)
      - Market data manager (streaming pipeline)
      - Staleness monitor (data quality)
      - IV engine and history (implied volatility analytics)
      - Earnings calendar (upcoming earnings events)
      - Risk repository, circuit breaker, and risk manager (risk engine)
      - Order execution service, fill tracker, and recovery manager (execution)
      - Agent pipeline deps and compiled LangGraph pipeline (AI agents)
      - Regime detector (market condition classification)
      - Expiration monitor (option position rolling logic)
      - Dashboard publisher (writes state to Redis for dashboard server)
      - Alert router, Slack/SMS notifiers, and approval manager (alerts & autonomy)
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
        self.market_data_manager: MarketDataManager | None = None
        self.staleness_monitor: StalenessMonitor | None = None
        self.iv_engine: IVEngine | None = None
        self.iv_history: IVHistoryManager | None = None
        self.earnings_calendar: EarningsCalendar | None = None
        self.risk_repository: RiskRepository | None = None
        self.circuit_breaker: CircuitBreaker | None = None
        self.risk_manager: RiskManager | None = None
        self.execution_service: OrderExecutionService | None = None
        self.fill_tracker: FillTracker | None = None
        self.order_recovery: OrderRecoveryManager | None = None
        # Phase 5: Agent pipeline
        self.pipeline_deps: PipelineDeps | None = None
        self.agent_pipeline = None
        # Phase 6: Regime detection and rolling
        self.regime_detector: RegimeDetector | None = None
        self.expiration_monitor: ExpirationMonitor | None = None
        # Phase 7: Dashboard publisher
        self.dashboard_publisher: DashboardPublisher | None = None
        # Phase 8: Alerts and autonomy
        self.alert_router: AlertRouter | None = None
        self.slack_notifier: SlackNotifier | None = None
        self.sms_notifier: SMSNotifier | None = None
        self.approval_manager: ApprovalManager | None = None
        self._alert_router_task: asyncio.Task | None = None

    async def startup(self) -> None:
        """Start the trading application.

        Configures logging, prints startup banner, and creates all
        Phase 1-5 components. Does NOT connect to IB -- call connect_ib()
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

        # Phase 2: Market Data components (wired but not started until IB connects)
        subscriber = SubscriptionManager(
            ib=self.connection_manager.ib,
            settings=self.settings,
        )
        distributor = RedisDistributor(redis_client=self.redis_client)
        writer = TimescaleDBWriter(
            session_factory=self.session_factory,
            settings=self.settings,
        )
        self.market_data_manager = MarketDataManager(
            ib=self.connection_manager.ib,
            subscriber=subscriber,
            distributor=distributor,
            writer=writer,
            settings=self.settings,
        )
        self.staleness_monitor = StalenessMonitor(
            subscriber=subscriber,
            distributor=distributor,
            settings=self.settings,
        )

        # Phase 2: Analytics components
        self.iv_history = IVHistoryManager(
            ib=self.connection_manager.ib,
            session_factory=self.session_factory,
            settings=self.settings,
        )
        self.iv_engine = IVEngine(
            iv_history=self.iv_history,
            settings=self.settings,
        )
        self.earnings_calendar = EarningsCalendar(
            session_factory=self.session_factory,
            settings=self.settings,
        )

        # Phase 3: Risk engine components
        self.risk_repository = RiskRepository(session_factory=self.session_factory)
        risk_profile = (
            self.settings.risk_limits.paper
            if self.settings.trading.mode == "paper"
            else self.settings.risk_limits.live
        )
        self.circuit_breaker = CircuitBreaker(
            redis=self.redis_client,
            repository=self.risk_repository,
            mode=self.settings.trading.mode,
            limits=risk_profile.loss,
        )
        self.risk_manager = RiskManager(
            limits=risk_profile,
            circuit_breaker=self.circuit_breaker,
            repository=self.risk_repository,
            ib=None,
            mode=self.settings.trading.mode,
        )

        # Phase 4: Order execution components
        self.fill_tracker = FillTracker(session_factory=self.session_factory)
        self.execution_service = OrderExecutionService(
            ib=self.connection_manager.ib,
            risk_manager=self.risk_manager,
            order_tracker=self.order_tracker,
            session_factory=self.session_factory,
        )
        self.execution_service.fill_tracker = self.fill_tracker
        self.order_recovery = OrderRecoveryManager(
            ib=self.connection_manager.ib,
            order_tracker=self.order_tracker,
            execution_service=self.execution_service,
            session_factory=self.session_factory,
        )

        # Phase 5: Agent pipeline dependencies (pipeline compiled in connect_ib)
        contract_cache = ContractCache(
            redis_client=self.redis_client,
            ttl=self.settings.redis.contract_cache_ttl,
        )
        contract_resolver = ContractResolver(
            ib=self.connection_manager.ib,
            cache=contract_cache,
        )
        self.pipeline_deps = PipelineDeps(
            iv_engine=self.iv_engine,
            earnings_calendar=self.earnings_calendar,
            contract_resolver=contract_resolver,
            risk_manager=self.risk_manager,
            execution_service=self.execution_service,
            redis_client=self.redis_client,
            session_factory=self.session_factory,
            settings=self.settings,
        )

        # Phase 7: Create dashboard publisher
        self.dashboard_publisher = DashboardPublisher(
            redis_client=self.redis_client,
            ib=self.connection_manager.ib,
            health_monitor=self.health_monitor,
            interval=self.settings.dashboard.publisher_interval,
        )

        # Phase 6: Create regime detector (non-critical)
        if self.settings.agents.regime.enabled:
            try:
                self.regime_detector = RegimeDetector(self.settings.agents.regime)
                self.pipeline_deps.regime_detector = self.regime_detector
                self.log.info("regime_detector.created")
            except Exception:
                self.log.warning("regime_detector.create_failed", exc_info=True)

        # Phase 8: Alert routing and approval management
        if (
            self.settings.alerts.slack_enabled
            and self.settings.alerts.slack_webhook_url
        ):
            self.slack_notifier = SlackNotifier(
                webhook_url=self.settings.alerts.slack_webhook_url,
            )

        if (
            self.settings.alerts.sms_enabled
            and self.settings.alerts.twilio_account_sid
            and self.settings.alerts.twilio_auth_token
            and self.settings.alerts.twilio_from_number
            and self.settings.alerts.twilio_to_number
        ):
            self.sms_notifier = SMSNotifier(
                account_sid=self.settings.alerts.twilio_account_sid,
                auth_token=self.settings.alerts.twilio_auth_token,
                from_number=self.settings.alerts.twilio_from_number,
                to_number=self.settings.alerts.twilio_to_number,
                cooldown_seconds=self.settings.alerts.sms_cooldown_seconds,
            )

        self.alert_router = AlertRouter(
            redis=self.redis_client,
            slack_notifier=self.slack_notifier,
            sms_notifier=self.sms_notifier,
            config=self.settings.alerts,
        )

        auto_thresholds = (
            self.settings.auto_execute.paper
            if self.settings.trading.mode == "paper"
            else self.settings.auto_execute.live
        )
        self.approval_manager = ApprovalManager(
            redis=self.redis_client,
            timeout_seconds=auto_thresholds.approval_timeout_seconds,
        )

        # Wire Phase 8 components into pipeline deps
        if self.pipeline_deps is not None:
            self.pipeline_deps.approval_manager = self.approval_manager
            self.pipeline_deps.auto_execute_thresholds = auto_thresholds

        self.log.info("startup.complete")

    async def connect_ib(self) -> None:
        """Connect to IB Gateway and start Phase 2-5 streaming components.

        Separated from startup() to allow testing without IB Gateway.
        Must call startup() first. After IB connects, starts market data
        streaming, bootstraps IV history, refreshes earnings calendar,
        restores circuit breaker state, recovers in-flight orders, and
        compiles the agent pipeline with checkpoint persistence.
        """
        if self.connection_manager is None:
            raise RuntimeError("Must call startup() before connect_ib()")
        await self.connection_manager.connect()

        # Start market data streaming after IB connection
        if self.market_data_manager is not None:
            await self.market_data_manager.start()
            self.log.info("market_data.streaming_started")

        if self.staleness_monitor is not None:
            await self.staleness_monitor.start()

        # Bootstrap IV history for watchlist (rate-limited, non-critical)
        if self.iv_history is not None:
            try:
                await self.iv_history.bootstrap_watchlist(
                    self.settings.market_data.watchlist
                )
                self.log.info("iv_history.bootstrap_complete")
            except Exception:
                self.log.warning("iv_history.bootstrap_failed", exc_info=True)

        # Refresh earnings calendar if stale (non-critical)
        if self.earnings_calendar is not None and self.earnings_calendar.needs_refresh():
            try:
                await self.earnings_calendar.refresh_watchlist(
                    self.settings.market_data.watchlist
                )
                self.log.info("earnings.refresh_complete")
            except Exception:
                self.log.warning("earnings.refresh_failed", exc_info=True)

        # Phase 3: Wire IB to risk manager and restore circuit breaker state
        if self.risk_manager is not None:
            self.risk_manager._ib = self.connection_manager.ib
        if self.circuit_breaker is not None:
            try:
                await self.circuit_breaker.load_from_db()
                self.log.info("circuit_breaker.state_restored")
            except Exception:
                self.log.warning("circuit_breaker.restore_failed", exc_info=True)

        # Phase 4: Recover in-flight orders after reconnect (non-critical)
        if self.order_recovery is not None:
            try:
                summary = await self.order_recovery.recover_after_reconnect()
                self.log.info("order_recovery.complete", **summary)
            except Exception:
                self.log.warning("order_recovery.failed", exc_info=True)

        # Phase 6: Create expiration monitor (non-critical, needs IB connection)
        if self.settings.agents.rolling.enabled:
            try:
                self.expiration_monitor = ExpirationMonitor(
                    ib=self.connection_manager.ib,
                    config=self.settings.agents.rolling,
                )
                if self.pipeline_deps is not None:
                    self.pipeline_deps.expiration_monitor = self.expiration_monitor
                self.log.info("expiration_monitor.created")
            except Exception:
                self.log.warning("expiration_monitor.create_failed", exc_info=True)

        # Phase 7: Start dashboard publisher (non-critical)
        if self.dashboard_publisher is not None:
            try:
                await self.dashboard_publisher.start()
                self.log.info("dashboard_publisher.started")
            except Exception:
                self.log.warning("dashboard_publisher.start_failed", exc_info=True)

        # Phase 8: Start alert router as background task (non-critical)
        if self.alert_router is not None:
            try:
                self._alert_router_task = asyncio.create_task(
                    self.alert_router.listen()
                )
                self.log.info("alert_router.started")
            except Exception:
                self.log.warning("alert_router.start_failed", exc_info=True)

        # Phase 8: Recover expired approvals from previous process (non-critical)
        if self.approval_manager is not None:
            try:
                count = await self.approval_manager.recover_expired()
                if count > 0:
                    self.log.info(
                        "approval_manager.recovered_expired", count=count
                    )
            except Exception:
                self.log.warning(
                    "approval_manager.recover_failed", exc_info=True
                )

        # Phase 5: Compile agent pipeline with checkpoint persistence (non-critical)
        if self.pipeline_deps is not None:
            try:
                checkpointer = await create_checkpointer(
                    self.settings.agents.checkpoint_conn_string
                )
                self.agent_pipeline = await create_pipeline(
                    deps=self.pipeline_deps,
                    checkpointer=checkpointer,
                )
                self.log.info("agent_pipeline.compiled")
            except Exception:
                self.log.warning("agent_pipeline.compile_failed", exc_info=True)
                # Fallback: compile without checkpointer
                try:
                    self.agent_pipeline = await create_pipeline(
                        deps=self.pipeline_deps,
                    )
                    self.log.info(
                        "agent_pipeline.compiled_without_checkpoint"
                    )
                except Exception:
                    self.log.warning(
                        "agent_pipeline.compile_fallback_failed",
                        exc_info=True,
                    )

    async def run_agent_pipeline(
        self,
        watchlist: list[str],
        account_value: float = 100_000.0,
    ) -> dict | None:
        """Run the agent pipeline with rolling pre-check.

        Single call-site for running the agent pipeline. Scans for
        expiring positions via ExpirationMonitor before invoking
        run_pipeline(), ensuring rolling candidates are always checked
        and injected into pipeline state.

        Args:
            watchlist: Symbols to scan for opportunities.
            account_value: Current account value for position sizing.

        Returns:
            The final PipelineState dict, or None if the pipeline is
            not compiled or an error occurs.
        """
        try:
            if self.agent_pipeline is None:
                self.log.warning("agent_pipeline.not_compiled")
                return None

            # Scan for rolling candidates (non-fatal if monitor unavailable)
            rolling_candidates: list[dict] = []
            if self.expiration_monitor is not None:
                try:
                    candidates = await self.expiration_monitor.scan_expiring_positions()
                    rolling_candidates = [c.model_dump() for c in candidates]
                except Exception:
                    self.log.warning(
                        "agent_pipeline.rolling_scan_failed", exc_info=True
                    )

            result = await run_pipeline(
                graph=self.agent_pipeline,
                watchlist=watchlist,
                account_value=account_value,
                rolling_candidates=rolling_candidates,
            )
            return result

        except Exception:
            self.log.error("agent_pipeline.run_failed", exc_info=True)
            return None

    async def shutdown(self) -> None:
        """Shut down the trading application.

        Stops Phase 2 market data components first (writer needs to flush
        before IB disconnects), then disconnects IB, closes Redis, and
        disposes the database engine. Each step is wrapped in try/except
        to ensure all cleanup runs even if individual steps fail.
        """
        self.log.info("shutdown.starting")

        # Phase 8: Cancel alert router background task
        if self._alert_router_task is not None:
            try:
                self._alert_router_task.cancel()
                try:
                    await self._alert_router_task
                except asyncio.CancelledError:
                    pass
            except Exception:
                self.log.warning(
                    "shutdown.alert_router_failed", exc_info=True
                )

        # Phase 7: Stop dashboard publisher before IB disconnect
        if self.dashboard_publisher is not None:
            try:
                await self.dashboard_publisher.stop()
            except Exception:
                self.log.warning("shutdown.dashboard_publisher_failed", exc_info=True)

        # Phase 2: Stop market data BEFORE IB disconnects (writer needs to flush)
        if self.staleness_monitor is not None:
            try:
                await self.staleness_monitor.stop()
            except Exception:
                self.log.warning("shutdown.staleness_monitor_failed", exc_info=True)

        if self.market_data_manager is not None:
            try:
                await self.market_data_manager.stop()
            except Exception:
                self.log.warning("shutdown.market_data_failed", exc_info=True)

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
