"""Layered configuration system for the trading platform.

Configuration loading order (highest priority wins):
  1. Environment variables (TRADING__SECTION__KEY format)
  2. Mode-specific YAML (config/paper.yml or config/live.yml)
  3. Default YAML (config/default.yml)
  4. Pydantic field defaults

The TRADING_MODE env var selects paper (default) or live mode.
Mode determines which YAML overlay is loaded and the IB Gateway port:
  - paper -> port 4002 (IB Gateway paper trading)
  - live  -> port 4001 (IB Gateway live trading)

Port note:
  IBConfig.port is the raw config override (not typically set directly).
  TradingConfig.ib_port is the DERIVED port from trading mode.
  Always use settings.trading.ib_port for the IB connection port.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import structlog
from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource
from pyaml_env import parse_config

from trading.agents.config import AgentConfig
from trading.alerts.config import AlertConfig, AutoExecuteConfig
from trading.risk.config import RiskLimitsConfig

logger = structlog.get_logger()

# Project root is 2 levels up from this file (src/trading/config.py -> project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


class TradingConfig(BaseModel):
    """Core trading mode configuration.

    The trading mode determines safety-critical behavior:
    - paper: connects to IB Gateway paper trading port (4002)
    - live: connects to IB Gateway live trading port (4001)

    Defaults to paper for safety. Any ambiguous/invalid value falls back to paper.
    """

    mode: Literal["paper", "live"] = "paper"

    @field_validator("mode", mode="before")
    @classmethod
    def validate_mode(cls, v: Any) -> str:
        """Default to paper if value is not exactly 'paper' or 'live'.

        Safety: ambiguous config always means paper trading.
        """
        if isinstance(v, str) and v.strip().lower() in ("paper", "live"):
            return v.strip().lower()
        return "paper"

    @property
    def ib_port(self) -> int:
        """Return the IB Gateway port for the current trading mode.

        - live: 4001
        - paper: 4002
        """
        return 4001 if self.mode == "live" else 4002


class IBConfig(BaseModel):
    """IB Gateway connection parameters.

    Note: The 'port' field here is rarely set directly. Use
    Settings.trading.ib_port to get the port derived from trading mode.
    This field exists as an explicit override escape hatch.
    """

    host: str = "127.0.0.1"
    port: int = 4002
    client_id: int = 1
    timeout: float = 30.0
    max_reconnect_attempts: int = 0  # 0 = infinite
    reconnect_delay: float = 5.0
    reconnect_max_delay: float = 120.0


class DatabaseConfig(BaseModel):
    """TimescaleDB/PostgreSQL connection configuration."""

    url: str = "postgresql+asyncpg://trading:trading@localhost:5432/trading"
    pool_size: int = 10
    pool_overflow: int = 5


class RedisConfig(BaseModel):
    """Redis connection and cache configuration."""

    url: str = "redis://localhost:6379/0"
    contract_cache_ttl: int = 3600


class LoggingConfig(BaseModel):
    """Logging output configuration."""

    level: str = "INFO"
    format: Literal["json", "console"] = "console"


class DashboardConfig(BaseModel):
    """Dashboard server configuration.

    Controls the FastAPI dashboard server settings including host, port,
    CORS origins, WebSocket ping interval, update throttling, and the
    interval at which DashboardPublisher writes to Redis.
    """

    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = ["http://localhost:3000"]
    ws_ping_interval: int = 30
    update_throttle_ms: int = 500
    publisher_interval: int = 5


class MarketDataConfig(BaseModel):
    """Market data streaming configuration.

    Controls watchlist symbols, subscription limits, staleness detection,
    batch persistence, and external API keys for the market data system.
    """

    watchlist: list[str] = ["SPY", "QQQ", "IWM", "AAPL", "MSFT"]
    max_subscription_lines: int = 100
    reserved_lines: int = 20
    staleness_threshold_seconds: int = 30
    batch_flush_interval_seconds: float = 5.0
    batch_size: int = 500
    iv_refresh_interval_minutes: int = 15
    earnings_lookout_days: int = 7
    finnhub_api_key: str = ""


def _load_yaml_config(trading_mode: str) -> dict[str, Any]:
    """Load and merge YAML configuration files.

    Loads config/default.yml first, then overlays mode-specific
    config (paper.yml or live.yml). Uses pyaml_env for ${ENV_VAR}
    interpolation in YAML values.

    Args:
        trading_mode: Either "paper" or "live".

    Returns:
        Merged configuration dictionary.
    """
    config: dict[str, Any] = {}

    # Load default config (default_value="" so missing env vars become empty strings
    # rather than pyaml-env's "N/A" default, matching pydantic field defaults)
    default_path = CONFIG_DIR / "default.yml"
    if default_path.exists():
        loaded = parse_config(str(default_path), default_value="")
        if loaded:
            config = loaded

    # Overlay mode-specific config
    mode_path = CONFIG_DIR / f"{trading_mode}.yml"
    if mode_path.exists():
        mode_config = parse_config(str(mode_path), default_value="")
        if mode_config:
            _deep_merge(config, mode_config)

    return config


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base, modifying base in place.

    For nested dicts, recursively merges. For all other types,
    override replaces base.
    """
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


class Settings(BaseSettings):
    """Root settings container with layered YAML + env var configuration.

    Loading priority (highest wins):
      1. Environment variables (TRADING__SECTION__KEY)
      2. Mode-specific YAML overlay (paper.yml / live.yml)
      3. Default YAML (default.yml)
      4. Field defaults in Pydantic models

    Usage:
        settings = Settings()  # Loads from YAML + env vars
        print(settings.trading.mode)      # "paper" or "live"
        print(settings.trading.ib_port)   # 4002 or 4001
    """

    trading: TradingConfig = TradingConfig()
    ib: IBConfig = IBConfig()
    database: DatabaseConfig = DatabaseConfig()
    redis: RedisConfig = RedisConfig()
    logging: LoggingConfig = LoggingConfig()
    market_data: MarketDataConfig = MarketDataConfig()
    agents: AgentConfig = AgentConfig()
    dashboard: DashboardConfig = DashboardConfig()
    risk_limits: RiskLimitsConfig = RiskLimitsConfig()
    alerts: AlertConfig = AlertConfig()
    auto_execute: AutoExecuteConfig = AutoExecuteConfig()

    model_config = {
        "env_prefix": "TRADING__",
        "env_nested_delimiter": "__",
    }

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Customise settings source priority.

        Order (first = highest priority):
          1. init_settings (explicit constructor args)
          2. env_settings (environment variables)
          3. YAML settings (loaded from files)
          4. file_secret_settings
        """
        return (
            init_settings,
            env_settings,
            YamlSettingsSource(settings_cls),
            file_secret_settings,
        )


class YamlSettingsSource(PydanticBaseSettingsSource):
    """Custom settings source that loads from YAML config files."""

    def get_field_value(
        self, field: Any, field_name: str
    ) -> tuple[Any, str, bool]:
        """Get a field value from YAML config.

        Returns (value, field_name, is_complex).
        """
        trading_mode = os.environ.get("TRADING_MODE", "paper").strip().lower()
        if trading_mode not in ("paper", "live"):
            trading_mode = "paper"

        yaml_config = _load_yaml_config(trading_mode)
        value = yaml_config.get(field_name)
        return value, field_name, bool(value and isinstance(value, dict))

    def __call__(self) -> dict[str, Any]:
        """Load all settings from YAML files."""
        trading_mode = os.environ.get("TRADING_MODE", "paper").strip().lower()
        if trading_mode not in ("paper", "live"):
            trading_mode = "paper"

        yaml_config = _load_yaml_config(trading_mode)
        return yaml_config
