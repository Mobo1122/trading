"""Risk engine: domain models, configuration, and orchestrator.

Provides the shared vocabulary for trade risk evaluation:
- TradeProposal/TradeLeg: Trade requests to evaluate
- RiskDecision/ViolatedRule: Evaluation results with reasons
- GreeksImpact/MarginResult: Supporting data structures
- RiskLimitsConfig: Paper/live risk limit profiles
- RiskManager: Single entry point for all trade risk evaluation
- evaluate_with_failsafe: Fail-safe wrapper guaranteeing explicit decisions
"""

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

__all__ = [
    "TradeProposal",
    "TradeLeg",
    "GreeksImpact",
    "RiskDecision",
    "ViolatedRule",
    "MarginResult",
    "RiskLimitsConfig",
    "RiskLimitsProfile",
    "RiskManager",
    "evaluate_with_failsafe",
]
