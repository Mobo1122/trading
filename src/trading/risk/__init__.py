"""Risk engine foundation: domain models and configuration.

Provides the shared vocabulary for trade risk evaluation:
- TradeProposal/TradeLeg: Trade requests to evaluate
- RiskDecision/ViolatedRule: Evaluation results with reasons
- GreeksImpact/MarginResult: Supporting data structures
- RiskLimitsConfig: Paper/live risk limit profiles
"""

from trading.risk.config import RiskLimitsConfig, RiskLimitsProfile
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
]
