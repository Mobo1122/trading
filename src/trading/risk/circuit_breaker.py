"""Circuit breaker for loss limit enforcement with halt state.

Tracks daily and weekly realized losses using Redis for hot-path access
and persists halt state to Postgres for crash recovery. Enforces:
- RISK-03: Daily/weekly loss limits halt new trade entries
- RISK-07: Halt state survives Redis/process restarts via Postgres

Loss accumulation uses Redis HINCRBYFLOAT for atomic increments.
Auto-reset occurs at US market open (9:30am ET) on appropriate boundaries.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import redis.asyncio as aioredis
import structlog

from trading.risk.config import LossLimits
from trading.risk.models import RiskDecision, ViolatedRule
from trading.risk.repository import RiskRepository


log = structlog.get_logger().bind(component="circuit_breaker")

ET = ZoneInfo("America/New_York")


class CircuitBreaker:
    """Loss limit circuit breaker with dual Redis + Postgres state.

    Redis provides sub-millisecond reads for the hot evaluation path.
    Postgres provides durable state for crash recovery. On startup,
    load_from_db() copies Postgres state into Redis so halts survive
    Redis restarts.

    Args:
        redis: Async Redis client (decode_responses=True).
        repository: RiskRepository for Postgres persistence.
        mode: Trading mode ('paper' or 'live').
        limits: LossLimits config with daily/weekly thresholds.
        emergency_halt: Whether emergency halt is active (from RiskLimitsProfile).
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        repository: RiskRepository,
        mode: str,
        limits: LossLimits,
        emergency_halt: bool = False,
    ) -> None:
        self._redis = redis
        self._repository = repository
        self._mode = mode
        self._limits = limits
        self._emergency_halt = emergency_halt
        self._key = f"risk:circuit_breaker:{mode}"

    async def check(self) -> RiskDecision | None:
        """Check if any halt is active, blocking new trade entries.

        Checks in order: emergency halt, daily halt, weekly halt.
        Returns a rejection RiskDecision if halted, or None if clear.

        Returns:
            RiskDecision with approved=False if halted, None otherwise.
        """
        # Emergency halt takes priority (config-driven, not loss-driven)
        if self._emergency_halt:
            return RiskDecision(
                approved=False,
                violated_rule=ViolatedRule.EMERGENCY_HALT,
                details="Emergency halt is active -- all trading suspended",
            )

        state = await self._redis.hgetall(self._key)
        if not state:
            return None

        if state.get("daily_halted") == "true":
            halted_at = state.get("halted_at", "unknown")
            daily_loss = state.get("daily_realized_loss", "0")
            return RiskDecision(
                approved=False,
                violated_rule=ViolatedRule.DAILY_LOSS_LIMIT,
                details=(
                    f"Daily loss limit breached: ${float(daily_loss):,.2f} "
                    f"(limit ${self._limits.daily_max_loss:,.2f}). "
                    f"Halted at {halted_at}"
                ),
            )

        if state.get("weekly_halted") == "true":
            halted_at = state.get("halted_at", "unknown")
            weekly_loss = state.get("weekly_realized_loss", "0")
            return RiskDecision(
                approved=False,
                violated_rule=ViolatedRule.WEEKLY_LOSS_LIMIT,
                details=(
                    f"Weekly loss limit breached: ${float(weekly_loss):,.2f} "
                    f"(limit ${self._limits.weekly_max_loss:,.2f}). "
                    f"Halted at {halted_at}"
                ),
            )

        return None

    async def record_realized_loss(self, loss_amount: float) -> None:
        """Record a realized loss and check if limits are breached.

        Uses Redis HINCRBYFLOAT for atomic increment of both daily and
        weekly accumulators. If either exceeds its threshold, activates
        the corresponding halt.

        Args:
            loss_amount: Positive dollar amount representing loss.
        """
        if loss_amount <= 0:
            return

        # Atomic increment of both accumulators
        daily_total = float(
            await self._redis.hincrbyfloat(
                self._key, "daily_realized_loss", loss_amount
            )
        )
        weekly_total = float(
            await self._redis.hincrbyfloat(
                self._key, "weekly_realized_loss", loss_amount
            )
        )

        log.info(
            "Realized loss recorded",
            loss_amount=loss_amount,
            daily_total=daily_total,
            weekly_total=weekly_total,
            mode=self._mode,
        )

        # Check thresholds and activate halts as needed
        if daily_total >= self._limits.daily_max_loss:
            await self._activate_halt("daily")

        if weekly_total >= self._limits.weekly_max_loss:
            await self._activate_halt("weekly")

    async def _activate_halt(self, halt_type: str) -> None:
        """Activate a circuit breaker halt in both Redis and Postgres.

        Sets the halt flag and timestamp in Redis for fast reads,
        then persists to Postgres for crash recovery.

        Args:
            halt_type: 'daily' or 'weekly'.
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        # Set halt state in Redis
        await self._redis.hset(
            self._key,
            mapping={
                f"{halt_type}_halted": "true",
                "halted_at": now_iso,
            },
        )

        # Read current loss values from Redis for Postgres persistence
        state = await self._redis.hgetall(self._key)
        daily_loss = float(state.get("daily_realized_loss", 0))
        weekly_loss = float(state.get("weekly_realized_loss", 0))

        # Persist to Postgres for crash recovery
        await self._repository.save_circuit_breaker_state(
            mode=self._mode,
            halt_type=halt_type,
            halted=True,
            halted_at=datetime.now(timezone.utc),
            daily_loss=daily_loss,
            weekly_loss=weekly_loss,
        )

        log.warning(
            "Circuit breaker activated",
            halt_type=halt_type,
            mode=self._mode,
            daily_loss=daily_loss,
            weekly_loss=weekly_loss,
        )

        # Publish alert event for alert router (non-fatal)
        try:
            await self._redis.publish(
                "alerts:circuit_breaker",
                json.dumps({
                    "halt_type": halt_type,
                    "reason": (
                        f"{halt_type.title()} loss limit breached "
                        f"(daily=${daily_loss:,.2f}, weekly=${weekly_loss:,.2f})"
                    ),
                    "mode": self._mode,
                    "timestamp": now_iso,
                }),
            )
        except Exception:
            log.warning(
                "circuit_breaker.alert_publish_failed",
                exc_info=True,
            )

    async def load_from_db(self) -> None:
        """Restore circuit breaker state from Postgres into Redis.

        Called on startup to ensure halt state survives Redis restarts.
        Loads all breaker records for this mode and writes their state
        (halt flag, timestamp, loss accumulators) into the Redis hash.
        """
        records = await self._repository.load_circuit_breaker_state(self._mode)

        for record in records:
            mapping: dict[str, str] = {
                f"{record.halt_type}_halted": "true" if record.halted else "false",
                "daily_realized_loss": str(record.daily_realized_loss),
                "weekly_realized_loss": str(record.weekly_realized_loss),
            }
            if record.halted and record.halted_at:
                mapping["halted_at"] = record.halted_at.isoformat()

            await self._redis.hset(self._key, mapping=mapping)

        log.info(
            "Circuit breaker state restored from DB",
            mode=self._mode,
            records_loaded=len(records),
        )

    async def check_and_reset(self) -> None:
        """Check if loss accumulators should be reset at market open.

        Daily reset: At 9:30am ET each trading day, clears daily loss
        and daily halt (but NOT weekly halt or weekly loss).

        Weekly reset: At 9:30am ET on Monday, clears weekly loss and
        weekly halt (but NOT daily halt or daily loss).

        Per RESEARCH.md Pitfall 5: daily reset does NOT clear weekly
        halt, and weekly reset does NOT clear daily halt.
        """
        now_et = datetime.now(timezone.utc).astimezone(ET)
        market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)

        # Only reset at or after market open
        if now_et < market_open:
            return

        state = await self._redis.hgetall(self._key)
        if not state:
            return

        # Daily reset: if last_reset_daily is not today
        last_reset_daily = state.get("last_reset_daily", "")
        today_str = now_et.date().isoformat()

        if last_reset_daily != today_str:
            await self._redis.hset(
                self._key,
                mapping={
                    "daily_realized_loss": "0",
                    "daily_halted": "false",
                    "last_reset_daily": today_str,
                },
            )

            # Persist cleared daily state to Postgres
            # Read current weekly values to preserve them
            weekly_loss = float(state.get("weekly_realized_loss", 0))
            await self._repository.save_circuit_breaker_state(
                mode=self._mode,
                halt_type="daily",
                halted=False,
                halted_at=None,
                daily_loss=0.0,
                weekly_loss=weekly_loss,
            )

            log.info(
                "Daily loss accumulator reset",
                mode=self._mode,
                previous_daily_loss=state.get("daily_realized_loss", "0"),
            )

        # Weekly reset: Monday at 9:30am ET
        is_monday = now_et.weekday() == 0
        last_reset_weekly = state.get("last_reset_weekly", "")
        this_monday_str = (
            now_et.date().isoformat()
            if is_monday
            else ""
        )

        if is_monday and last_reset_weekly != this_monday_str:
            await self._redis.hset(
                self._key,
                mapping={
                    "weekly_realized_loss": "0",
                    "weekly_halted": "false",
                    "last_reset_weekly": this_monday_str,
                },
            )

            # Persist cleared weekly state to Postgres
            # Read current daily values to preserve them (may have just been reset above)
            refreshed = await self._redis.hgetall(self._key)
            daily_loss = float(refreshed.get("daily_realized_loss", 0))
            await self._repository.save_circuit_breaker_state(
                mode=self._mode,
                halt_type="weekly",
                halted=False,
                halted_at=None,
                daily_loss=daily_loss,
                weekly_loss=0.0,
            )

            log.info(
                "Weekly loss accumulator reset",
                mode=self._mode,
                previous_weekly_loss=state.get("weekly_realized_loss", "0"),
            )
