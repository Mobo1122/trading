"""Risk engine: domain models, configuration, and orchestrator.

Provides the shared vocabulary for trade risk evaluation:
- TradeProposal/TradeLeg: Trade requests to evaluate
- RiskDecision/ViolatedRule: Evaluation results with reasons
- GreeksImpact/MarginResult: Supporting data structures
- RiskLimitsConfig: Paper/live risk limit profiles
- RiskManager: Single entry point for all trade risk evaluation
- evaluate_with_failsafe: Fail-safe wrapper guaranteeing explicit decisions
- CircuitBreaker: Daily/weekly loss limit circuit breaker
- RiskRepository: Persistence for risk decisions and circuit breaker state
"""

from trading.risk.circuit_breaker import CircuitBreaker
from trading.risk.config import RiskLimitsConfig, RiskLimitsProfile
from trading.risk.manager import RiskManager, evaluate_with_failsafe
from trading.risk.models import (
    GreeksImpact,
    MarginResult,
    RiskDecision,
    TradeLeg,
    TradeProposal,
    ViolatedRule,
)
from trading.risk.repository import RiskRepository

__all__ = [
    "CircuitBreaker",
    "TradeProposal",
    "TradeLeg",
    "GreeksImpact",
    "RiskDecision",
    "ViolatedRule",
    "MarginResult",
    "RiskLimitsConfig",
    "RiskLimitsProfile",
    "RiskManager",
    "RiskRepository",
    "evaluate_with_failsafe",
]
